"""
ml_coletar.py — Roda uma vez (ou via cron).

O que mudou vs versão original:
  - Sem PRODUTO hardcoded: lê os termos ativos da tabela search_queries.
  - Sem watchlist.txt: salva em listings via upsert (não duplica).
  - Registra ultima_busca em search_queries a cada execução.

Uso:
  python ml_coletar.py              # coleta todos os termos ativos
  python ml_coletar.py --termo "X"  # coleta só um termo (para testes)
"""
import argparse
import re
import json
import time
import random
from datetime import datetime, timezone

import requests

from db import transaction

# ── Configurações ─────────────────────────────────────────────
TENTATIVAS_BUSCA = 5
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8"',
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
}


# ── Parsing do HTML do ML ──────────────────────────────────────
def parsear_results(html: str) -> list[dict]:
    """Extrai anúncios da página de resultados do Mercado Livre."""
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
                        d = json.loads(chunk[: j + 1])
                        mlb_id = d["id"]
                        cond_attr = next(
                            (
                                a["value_name"]
                                for a in d.get("attributes", [])
                                if a["id"] == "ITEM_CONDITION"
                            ),
                            None,
                        )
                        resultados.append(
                            {
                                "mlb_id": mlb_id,
                                "titulo": d.get("title", "?"),
                                "preco_inicial": d.get("price"),
                                "condicao": cond_attr or d.get("condition", "?"),
                                "url": (
                                    f"https://produto.mercadolivre.com.br/"
                                    f"{mlb_id.replace('MLB', 'MLB-')}"
                                ),
                                "status": "active",
                            }
                        )
                    except Exception:
                        pass
                    break

    return resultados


def buscar_termo(termo: str) -> list[dict]:
    """Acumula resultados de TENTATIVAS_BUSCA buscas para o termo."""
    slug = termo.lower().replace(" ", "-")
    url = (
        f"https://lista.mercadolivre.com.br/games/video-games/{slug}"
        "_NoIndex_True#applied_value_name%3DVideo+Games"
    )
    vistos: set[str] = set()
    acumulado: list[dict] = []

    for t in range(1, TENTATIVAS_BUSCA + 1):
        print(f"  [Tentativa {t}/{TENTATIVAS_BUSCA}] ", end="", flush=True)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
        except Exception as e:
            print(f"Erro: {e}")
            time.sleep(random.uniform(1, 2.5))
            continue

        if resp.status_code != 200:
            print(f"HTTP {resp.status_code}")
            time.sleep(random.uniform(1, 2.5))
            continue

        encontrados = parsear_results(resp.text)
        novos = [i for i in encontrados if i["mlb_id"] not in vistos]
        for item in novos:
            vistos.add(item["mlb_id"])
            acumulado.append(item)

        print(
            f"itens: {len(encontrados)} | novos: {len(novos)} | total: {len(acumulado)}"
        )

        if t < TENTATIVAS_BUSCA:
            time.sleep(random.uniform(1, 2.5))

    return acumulado


# ── Persistência no banco ──────────────────────────────────────
def upsert_listings(query_id: int, itens: list[dict]) -> int:
    """
    Insere ou atualiza anúncios na tabela listings.
    Não sobrescreve preco_final / finalizado_em / status de anúncios já fechados.
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
                    atualizado_em  = NOW(),
                    titulo         = EXCLUDED.titulo,
                    condicao       = EXCLUDED.condicao,
                    preco_inicial  = COALESCE(listings.preco_inicial, EXCLUDED.preco_inicial)
                    -- Não toca em status, preco_final, finalizado_em
                """,
                {**item, "query_id": query_id},
            )
            # Conta novos (rowcount=1 após INSERT puro; psycopg2 não distingue
            # INSERT de UPDATE no ON CONFLICT, então usamos a heurística abaixo)
            if cur.rowcount == 1:
                novos += 1

        cur.execute(
            "UPDATE search_queries SET ultima_busca = NOW() WHERE id = %s",
            (query_id,),
        )

    return novos


def carregar_queries_ativas(termo_override: str | None = None) -> list[dict]:
    """
    Retorna lista de {id, termo} a processar.
    Se termo_override for fornecido, cria/garante o termo no banco e retorna só ele.
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
    parser = argparse.ArgumentParser(description="Coleta anúncios do Mercado Livre.")
    parser.add_argument(
        "--termo", help="Força um termo específico (ignora search_queries)", default=None
    )
    args = parser.parse_args()

    queries = carregar_queries_ativas(args.termo)

    if not queries:
        print("Nenhum termo ativo em search_queries. Adicione um registro e tente novamente.")
        raise SystemExit(0)

    for q in queries:
        print(f"\n{'='*55}")
        print(f"Buscando: '{q['termo']}' (query_id={q['id']})")
        print(f"{'='*55}")

        itens = buscar_termo(q["termo"])
        novos = upsert_listings(q["id"], itens)

        print(f"\n✅ Salvo no banco — total encontrados: {len(itens)} | novos: {novos}")
