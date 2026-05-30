"""
api.py — FastAPI que expõe os dados do banco para o frontend (Loveable).

Endpoints:
  GET  /health            — health check (Render usa pra saber se subiu)
  GET  /listings          — lista anúncios com filtros
  GET  /listings/{mlb_id}/history  — histórico de preços
  GET  /watchlist         — termos monitorados (search_queries)
  POST /watchlist         — adiciona novo termo
  PUT  /watchlist/{id}    — ativa/pausa um termo
  DELETE /watchlist/{id}  — remove um termo
  GET  /stats             — resumo para o dashboard

Rodar local:
  uvicorn api:app --reload

No Render: use uvicorn api:app --host 0.0.0.0 --port $PORT
"""
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from db import transaction

app = FastAPI(title="Price Compass API", version="1.0")

# ── CORS ───────────────────────────────────────────────────────
# Em produção, substitua "*" pela URL do seu frontend no Loveable/Render
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── /health ────────────────────────────────────────────────────
@app.get("/health")
def health():
    """Health check — Render usa este endpoint para confirmar que a API subiu."""
    return {"status": "ok"}


# ── /listings ─────────────────────────────────────────────────
@app.get("/listings")
def get_listings(
    status: Optional[str] = Query(None, description="'active' | 'closed'"),
    query_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None, description="Busca no título"),
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    """Retorna anúncios. Suporta filtro por status, query_id e busca textual."""
    conditions = []
    params: dict = {"limit": limit, "offset": offset}

    if status:
        conditions.append("l.status = %(status)s")
        params["status"] = status
    if query_id is not None:
        conditions.append("l.query_id = %(query_id)s")
        params["query_id"] = query_id
    if q:
        conditions.append("l.titulo ILIKE %(q)s")
        params["q"] = f"%{q}%"

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with transaction() as cur:
        cur.execute(
            f"""
            SELECT
                l.mlb_id,
                l.titulo,
                l.url,
                l.condicao,
                l.status,
                l.preco_inicial,
                l.preco_final,
                l.finalizado_em,
                l.capturado_em,
                l.atualizado_em,
                sq.termo AS query_termo
            FROM listings l
            LEFT JOIN search_queries sq ON sq.id = l.query_id
            {where}
            ORDER BY l.atualizado_em DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            params,
        )
        rows = [dict(r) for r in cur.fetchall()]

        cur.execute(
            f"SELECT COUNT(*) AS total FROM listings l {where}",
            params,
        )
        total = cur.fetchone()["total"]

    return {"total": total, "data": rows}


# ── /listings/{mlb_id}/history ────────────────────────────────
@app.get("/listings/{mlb_id}/history")
def get_history(mlb_id: str):
    """Retorna o histórico de preços de um anúncio específico."""
    with transaction() as cur:
        cur.execute(
            """
            SELECT preco, evento, condicao, fonte, registrado_em
            FROM price_history
            WHERE mlb_id = %s
            ORDER BY registrado_em ASC
            """,
            (mlb_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]

    return {"mlb_id": mlb_id, "history": rows}


# ── /watchlist (search_queries) ───────────────────────────────
@app.get("/watchlist")
def get_watchlist():
    """Lista todos os termos de busca."""
    with transaction() as cur:
        cur.execute(
            """
            SELECT
                sq.id,
                sq.termo,
                sq.ativo,
                sq.ultima_busca,
                sq.criado_em,
                COUNT(l.mlb_id)                                     AS total_anuncios,
                COUNT(l.mlb_id) FILTER (WHERE l.status = 'active')  AS ativos,
                COUNT(l.mlb_id) FILTER (WHERE l.status = 'closed')  AS fechados
            FROM search_queries sq
            LEFT JOIN listings l ON l.query_id = sq.id
            GROUP BY sq.id
            ORDER BY sq.criado_em DESC
            """
        )
        return [dict(r) for r in cur.fetchall()]


class WatchlistCreate(BaseModel):
    termo: str


@app.post("/watchlist", status_code=201)
def create_watchlist(body: WatchlistCreate):
    """Adiciona um novo termo de busca."""
    termo = body.termo.strip()
    if not termo:
        raise HTTPException(400, "Termo não pode ser vazio.")

    with transaction() as cur:
        cur.execute(
            """
            INSERT INTO search_queries (termo, ativo)
            VALUES (%s, TRUE)
            ON CONFLICT (termo) DO UPDATE SET ativo = TRUE
            RETURNING id, termo, ativo, criado_em
            """,
            (termo,),
        )
        row = dict(cur.fetchone())

    return row


class WatchlistUpdate(BaseModel):
    ativo: bool


@app.put("/watchlist/{query_id}")
def update_watchlist(query_id: int, body: WatchlistUpdate):
    """Ativa ou pausa um termo de busca."""
    with transaction() as cur:
        cur.execute(
            "UPDATE search_queries SET ativo = %s WHERE id = %s RETURNING id, termo, ativo",
            (body.ativo, query_id),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(404, "Termo não encontrado.")
    return dict(row)


@app.delete("/watchlist/{query_id}", status_code=204)
def delete_watchlist(query_id: int):
    """Remove um termo. Os listings associados ficam com query_id = NULL."""
    with transaction() as cur:
        cur.execute("DELETE FROM search_queries WHERE id = %s RETURNING id", (query_id,))
        row = cur.fetchone()

    if not row:
        raise HTTPException(404, "Termo não encontrado.")


# ── /stats (resumo para o dashboard) ─────────────────────────
@app.get("/stats")
def get_stats():
    """Resumo geral para o dashboard do frontend."""
    with transaction() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*)                                         AS total,
                COUNT(*) FILTER (WHERE status = 'active')       AS ativos,
                COUNT(*) FILTER (WHERE status = 'closed')       AS fechados,
                ROUND(AVG(preco_final) FILTER (WHERE preco_final IS NOT NULL), 2) AS preco_medio_venda,
                MAX(finalizado_em)                               AS ultima_venda
            FROM listings
            """
        )
        stats = dict(cur.fetchone())

        cur.execute(
            """
            SELECT mlb_id, titulo, preco_final, finalizado_em, condicao
            FROM listings
            WHERE status = 'closed' AND finalizado_em IS NOT NULL
            ORDER BY finalizado_em DESC
            LIMIT 10
            """
        )
        stats["vendas_recentes"] = [dict(r) for r in cur.fetchall()]

    return stats
