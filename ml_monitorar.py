"""
ml_monitorar.py — Roda em loop (ou via cron a cada N minutos).

O que mudou vs versão original:
  - Sem watchlist.txt / vendidos.txt: lê e escreve direto no Postgres.
  - Ao detectar fechamento: atualiza listings + insere linha em price_history.
  - Nenhum arquivo é gerado; tudo persistido no banco.

Uso:
  python ml_monitorar.py               # loop infinito, intervalo padrão
  python ml_monitorar.py --intervalo 120  # intervalo em segundos
  python ml_monitorar.py --uma-vez     # roda um ciclo e sai (para cron externo)
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
INTERVALO_SEGUNDOS_PADRAO = 60

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


# ── Verificação de um anúncio individual ──────────────────────
def verificar_item(mlb_id: str) -> dict | None:
    """
    Acessa a página do anúncio e retorna {'status': ..., 'preco': ...}.
    Retorna None em caso de erro de rede.
    """
    url = f"https://produto.mercadolivre.com.br/{mlb_id.replace('MLB', 'MLB-')}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
    except Exception:
        return None

    html = resp.text

    # Tenta extrair via melidata (mais confiável)
    m = re.search(r'melidata\("add","event_data",(\{.*?\})\)', html, re.DOTALL)
    if m:
        try:
            d = json.loads(m.group(1))
            return {
                "status": d.get("item_status", "?"),
                "preco": d.get("price") or d.get("localItemPrice"),
            }
        except Exception:
            pass

    # Fallback: heurística no HTML
    status = "closed" if "finalizado" in html.lower() else "active"
    precos = re.findall(r'"price"\s*:\s*([\d.]+)', html)
    return {"status": status, "preco": float(precos[0]) if precos else None}


# ── Leitura e escrita no banco ─────────────────────────────────
def carregar_ativos() -> list[dict]:
    """Retorna todos os listings com status='active'."""
    with transaction() as cur:
        cur.execute(
            """
            SELECT mlb_id, titulo, preco_inicial, condicao
            FROM listings
            WHERE status = 'active'
            ORDER BY capturado_em
            """
        )
        return [dict(row) for row in cur.fetchall()]


def marcar_como_vendido(mlb_id: str, preco_final: float | None, condicao: str | None):
    """
    Atualiza o listings para 'closed' e insere linha de histórico.
    Usa upsert simples: se rodar de novo com o mesmo mlb_id fechado, não duplica o history
    porque a query principal só processa ativos.
    """
    agora = datetime.now(timezone.utc)
    with transaction() as cur:
        cur.execute(
            """
            UPDATE listings
            SET status        = 'closed',
                preco_final   = %s,
                finalizado_em = %s,
                atualizado_em = NOW()
            WHERE mlb_id = %s AND status = 'active'
            """,
            (preco_final, agora, mlb_id),
        )
        if cur.rowcount == 0:
            # Já foi marcado por outro processo, não duplica
            return

        cur.execute(
            """
            INSERT INTO price_history (mlb_id, preco, evento, condicao)
            VALUES (%s, %s, 'sold', %s)
            """,
            (mlb_id, preco_final, condicao),
        )


# ── Ciclo principal ────────────────────────────────────────────
def rodar_ciclo():
    agora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*55}")
    print(f"Ciclo — {agora_str}")
    print(f"{'='*55}")

    ativos = carregar_ativos()
    print(f"Itens ativos para checar: {len(ativos)}\n")

    recém_fechados = []

    for i, dados in enumerate(ativos, 1):
        mlb_id = dados["mlb_id"]
        print(
            f"[{i}/{len(ativos)}] {mlb_id} — {dados['titulo'][:45]}",
            end="  ",
            flush=True,
        )

        info = verificar_item(mlb_id)
        if info is None:
            print("❌ erro de rede")
            time.sleep(random.uniform(0.5, 1.2))
            continue

        if info["status"] == "closed":
            marcar_como_vendido(mlb_id, info["preco"], dados.get("condicao"))
            recém_fechados.append({**dados, "preco_final": info["preco"]})
            print(f"🔴 VENDIDO — R$ {info['preco']} — {dados.get('condicao', '?')}")
        else:
            print(f"🟢 ativo — R$ {dados.get('preco_inicial')}")

        time.sleep(random.uniform(0.5, 1.2))

    print(f"\n{'─'*55}")
    if recém_fechados:
        print("🔴 Vendidos nesta rodada:")
        for d in recém_fechados:
            print(f"  • {d['titulo']}")
            print(f"    R$ {d['preco_final']} | {d.get('condicao', '?')}")
    else:
        print("Nenhuma venda detectada.")


# ── Entry point ────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monitora anúncios ativos no ML.")
    parser.add_argument(
        "--intervalo",
        type=int,
        default=INTERVALO_SEGUNDOS_PADRAO,
        help="Segundos entre checagens (padrão: 60)",
    )
    parser.add_argument(
        "--uma-vez",
        action="store_true",
        help="Roda apenas um ciclo e encerra (útil com cron externo)",
    )
    args = parser.parse_args()

    if args.uma_vez:
        rodar_ciclo()
    else:
        print("Monitor iniciado. Ctrl+C para parar.")
        print(f"Lendo de 'listings' (status=active) | Intervalo: {args.intervalo}s\n")
        try:
            while True:
                rodar_ciclo()
                print(f"\nPróxima checagem em {args.intervalo}s...")
                time.sleep(args.intervalo)
        except KeyboardInterrupt:
            print("\n\nMonitor encerrado.")
