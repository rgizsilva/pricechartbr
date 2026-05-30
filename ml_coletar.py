"""
ml_coletar.py — Roda uma vez (ou via cron).

Usa Playwright (Chromium) para burlar o challenge Anubis do ML.
Lê os termos ativos da tabela search_queries e salva em listings via upsert.

Uso:
  python ml_coletar.py              # coleta todos os termos ativos
  python ml_coletar.py --termo "X"  # coleta só um termo (para testes)

PRÉ-REQUISITOS:
  pip install playwright
  playwright install chromium
"""
import argparse
import re
import json
import time
import random
import os
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

from db import transaction

# ── Configurações ─────────────────────────────────────────────
TENTATIVAS_BUSCA = 5

# Perfil persistente — evita o challenge Anubis nas próximas execuções
CHROME_PROFILE = os.environ.get(
    "CHROME_PROFILE",
    f"/home/{os.environ.get('USER', 'ubuntu')}/.chrome-ml"
)
CHROME_BIN = os.environ.get("CHROME_BIN", None)  # None = Chromium do Playwright


# ── Parsing do HTML / initialState do ML ──────────────────────
def extrair_initialstate(html: str) -> dict:
    """Extrai o objeto initialState embutido no HTML da página de busca do ML."""
    match = re.search(r'"initialState"\s*:\s*(\{)', html)
    if not match:
        return {}
    start = match.start(1)
    depth = 0
    for i, c in enumerate(html[start:], start):
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:i + 1])
                except Exception:
                    return {}
    return {}


def parsear_results_polycard(html: str) -> list[dict]:
    """
    Parser principal: estrutura initialState.results[].polycard (ML 2026).
    """
    state = extrair_initialstate(html)
    results = state.get("results", [])
    parsed = []

    for entry in results:
        if entry.get("id") != "POLYCARD":
            continue

        poly = entry.get("polycard", {})
        meta = poly.get("metadata", {})
        item_id = meta.get("id", "")
        if not item_id.startswith("MLB"):
            continue

        components = poly.get("components", [])

        titulo = next(
            (c["title"]["text"] for c in components
             if c.get("type") == "title" and "title" in c),
            "?"
        )

        preco = None
        price_comp = next((c for c in components if c.get("type") == "price"), None)
        if price_comp:
            preco = price_comp.get("price", {}).get("current_price", {}).get("value")

        condicao = next(
            (c.get("item_condition", {}).get("text")
             for c in components if c.get("type") == "item_condition"),
            "?"
        ) or "?"

        url = "https://" + meta.get("url", "").lstrip("/")

        parsed.append({
            "mlb_id":        item_id,
            "titulo":        titulo,
            "preco_inicial": preco,
            "condicao":      condicao,
            "url":           url,
            "status":        "active",
        })

    return parsed


def parsear_results_legado(html: str) -> list[dict]:
    """
    Fallback: parser legado para estrutura antiga do ML (results[].type=ITEM).
    """
    pos = html.find('"results":[{"id":"MLB')
    if pos == -1:
        return []

    trecho = html[pos:pos + 400_000]
    starts = [m.start() for m in re.finditer(r'\{"id":"MLB\d+","type":"ITEM"', trecho)]
    resultados = []

    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(trecho)
        chunk = trecho[start:end].rstrip(",")
        depth = 0
        for j, c in enumerate(chunk):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        d = json.loads(chunk[:j + 1])
                        mlb_id = d["id"]
                        cond_attr = next(
                            (a["value_name"] for a in d.get("attributes", [])
                             if a["id"] == "ITEM_CONDITION"),
                            None,
                        )
                        resultados.append({
                            "mlb_id":        mlb_id,
                            "titulo":        d.get("title", "?"),
                            "preco_inicial": d.get("price"),
                            "condicao":      cond_attr or d.get("condition", "?"),
                            "url": (
                                f"https://produto.mercadolivre.com.br/"
                                f"{mlb_id.replace('MLB', 'MLB-')}"
                            ),
                            "status": "active",
                        })
                    except Exception:
                        pass
                    break

    return resultados


def parsear_html(html: str) -> list[dict]:
    """Tenta o parser moderno; se retornar vazio, tenta o legado."""
    itens = parsear_results_polycard(html)
    if not itens:
        itens = parsear_results_legado(html)
    return itens


# ── Captura com Playwright (trata challenge Anubis) ────────────
def capturar_html(page, url: str) -> str | None:
    """
    Navega para a URL tratando o challenge Anubis do ML.
    Retorna o HTML com initialState, ou None se falhar.
    """
    html_capturado = []

    def handle_response(response):
        url_sem_hash   = url.split("#")[0]
        resp_sem_hash  = response.url.split("#")[0]
        if (resp_sem_hash == url_sem_hash
                and response.status == 200
                and "text/html" in response.headers.get("content-type", "")):
            try:
                html_capturado.append(response.body().decode("utf-8", errors="replace"))
            except Exception:
                pass

    page.on("response", handle_response)
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)

    # Aguarda challenge Anubis se aparecer
    try:
        if page.locator("#continue-button").count() > 0:
            print("challenge, aguardando...", end=" ", flush=True)
            page.wait_for_selector("#continue-button", state="hidden", timeout=20_000)
            page.wait_for_load_state("networkidle", timeout=20_000)
            print("ok.", end=" ", flush=True)
    except Exception as e:
        print(f"timeout challenge: {e}", end=" ", flush=True)

    page.remove_listener("response", handle_response)

    if "account-verification" in page.url:
        print("bloqueado (account-verification)")
        return None

    # 1ª opção: HTML raw capturado da resposta HTTP
    html = next((h for h in html_capturado if '"initialState"' in h), None)

    # 2ª opção: DOM renderizado pelo JS
    if not html:
        dom = page.content()
        if '"initialState"' in dom:
            html = dom

    # 3ª opção: evaluar initialState direto do JS da página
    if not html:
        try:
            state_js = page.evaluate("""
                () => {
                    const scripts = Array.from(document.querySelectorAll('script'));
                    for (const s of scripts) {
                        if (s.textContent.includes('"initialState"')) return s.textContent;
                    }
                    if (window.__PRELOADED_STATE__) return JSON.stringify({initialState: window.__PRELOADED_STATE__});
                    if (window.initialState)        return JSON.stringify({initialState: window.initialState});
                    return null;
                }
            """)
            if state_js and '"initialState"' in state_js:
                html = state_js
                print("[JS eval] ", end="", flush=True)
        except Exception as e:
            print(f"[JS eval falhou: {e}] ", end="", flush=True)

    return html


def buscar_termo(termo: str) -> list[dict]:
    """
    Abre o Playwright, busca o termo no ML e retorna lista de anúncios.
    Usa perfil persistente para não precisar resolver o challenge toda vez.
    """
    slug = termo.lower().replace(" ", "-")
    url  = (
        f"https://lista.mercadolivre.com.br/games/video-games/{slug}"
        "_NoIndex_True#applied_value_name%3DVideo+Games"
    )
    acumulado: dict[str, dict] = {}  # mlb_id → dados (deduplica)

    with sync_playwright() as p:
        launch_kwargs = dict(
            user_data_dir=CHROME_PROFILE,
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--headless=new",
                "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            ],
            locale="pt-BR",
            viewport={"width": 1280, "height": 800},
            extra_http_headers={
                "sec-ch-ua":          '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "sec-ch-ua-mobile":   "?0",
                "sec-ch-ua-platform": '"Linux"',
                "Accept-Language":    "pt-BR,pt;q=0.9",
            },
        )
        if CHROME_BIN:
            launch_kwargs["executable_path"] = CHROME_BIN

        ctx = p.chromium.launch_persistent_context(**launch_kwargs)
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins',   {get: () => [1,2,3]});
            Object.defineProperty(navigator, 'languages', {get: () => ['pt-BR','pt','en-US']});
            window.chrome = { runtime: {} };
        """)
        page = ctx.new_page()

        for t in range(1, TENTATIVAS_BUSCA + 1):
            print(f"  [Tentativa {t}/{TENTATIVAS_BUSCA}] ", end="", flush=True)
            try:
                html = capturar_html(page, url)

                if not html:
                    print("sem initialState, pulando.")
                else:
                    encontrados = parsear_html(html)
                    novos = sum(1 for i in encontrados if i["mlb_id"] not in acumulado)
                    for item in encontrados:
                        acumulado[item["mlb_id"]] = item
                    print(
                        f"itens: {len(encontrados)} | novos: {novos} | total: {len(acumulado)}"
                    )
                    if encontrados:
                        break  # achou resultados, não precisa repetir

            except Exception as e:
                print(f"Erro: {e}")

            if t < TENTATIVAS_BUSCA:
                time.sleep(random.uniform(3, 6))

        try:
            ctx.close()
        except Exception:
            pass

    return list(acumulado.values())


# ── Persistência no banco ──────────────────────────────────────
def upsert_listings(query_id: int, itens: list[dict]) -> int:
    """
    Insere ou atualiza anúncios em listings.
    Não sobrescreve status/preco_final/finalizado_em de anúncios já fechados.
    Retorna quantos foram inseridos pela primeira vez.
    """
    novos = 0
    with transaction() as cur:
        for item in itens:
            cur.execute(
                """
                INSERT INTO listings
                    (mlb_id, query_id, titulo, url, condicao,
                     status, preco_inicial, atualizado_em)
                VALUES
                    (%(mlb_id)s, %(query_id)s, %(titulo)s, %(url)s, %(condicao)s,
                     'active', %(preco_inicial)s, NOW())
                ON CONFLICT (mlb_id) DO UPDATE SET
                    atualizado_em = NOW(),
                    titulo        = EXCLUDED.titulo,
                    condicao      = EXCLUDED.condicao,
                    preco_inicial = COALESCE(listings.preco_inicial, EXCLUDED.preco_inicial)
                """,
                {**item, "query_id": query_id},
            )
            if cur.rowcount == 1:
                novos += 1

        cur.execute(
            "UPDATE search_queries SET ultima_busca = NOW() WHERE id = %s",
            (query_id,),
        )

    return novos


def carregar_queries_ativas(termo_override: str | None = None) -> list[dict]:
    """
    Retorna {id, termo} dos termos a processar.
    Se termo_override for fornecido, garante o termo no banco e retorna só ele.
    """
    with transaction() as cur:
        if termo_override:
            cur.execute(
                """
                INSERT INTO search_queries (termo, ativo)
                VALUES (%s, TRUE)
                ON CONFLICT (termo) DO UPDATE SET ativo = TRUE
                RETURNING id, termo
                """,
                (termo_override,),
            )
        else:
            cur.execute(
                "SELECT id, termo FROM search_queries WHERE ativo = TRUE ORDER BY id"
            )
        return [dict(row) for row in cur.fetchall()]


# ── Main ───────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Coleta anúncios do ML → banco.")
    parser.add_argument("--termo", default=None, help="Força um termo específico")
    args = parser.parse_args()

    queries = carregar_queries_ativas(args.termo)

    if not queries:
        print("Nenhum termo ativo em search_queries.")
        raise SystemExit(0)

    for q in queries:
        print(f"\n{'='*55}")
        print(f"Buscando: '{q['termo']}' (query_id={q['id']})")
        print(f"{'='*55}")

        itens = buscar_termo(q["termo"])

        if not itens:
            print("\n⚠️  Nenhum item encontrado. Possíveis causas:")
            print("   - Challenge Anubis não resolveu (rode com headless=False uma vez)")
            print("   - Estrutura do ML mudou (verifique parsear_results_polycard)")
            print("   - IP bloqueado temporariamente")
            continue

        novos = upsert_listings(q["id"], itens)
        print(f"\n✅ Salvo no banco — encontrados: {len(itens)} | novos: {novos}")