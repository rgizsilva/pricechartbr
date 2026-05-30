/**
 * src/lib/api.ts
 *
 * Serviço que conecta o frontend ao backend FastAPI.
 * Configure a variável de ambiente VITE_API_URL no Loveable/Vite:
 *   VITE_API_URL=https://seu-backend.onrender.com
 *
 * Em dev local: crie .env.local com VITE_API_URL=http://localhost:8000
 */

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// ── Tipos espelhando o banco ────────────────────────────────────

export type ListingStatus = "active" | "closed";

export interface Listing {
  mlb_id: string;
  titulo: string;
  url: string;
  condicao: string | null;
  status: ListingStatus;
  preco_inicial: number | null;
  preco_final: number | null;
  finalizado_em: string | null;
  capturado_em: string;
  atualizado_em: string;
  query_termo: string | null;
}

export interface PricePoint {
  preco: number;
  evento: "sold" | "check" | "manual";
  condicao: string | null;
  fonte: string;
  registrado_em: string;
}

export interface SearchQuery {
  id: number;
  termo: string;
  ativo: boolean;
  ultima_busca: string | null;
  criado_em: string;
  total_anuncios: number;
  ativos: number;
  fechados: number;
}

export interface Stats {
  total: number;
  ativos: number;
  fechados: number;
  preco_medio_venda: number | null;
  ultima_venda: string | null;
  vendas_recentes: {
    mlb_id: string;
    titulo: string;
    preco_final: number | null;
    finalizado_em: string | null;
    condicao: string | null;
  }[];
}

// ── Helper interno ──────────────────────────────────────────────

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

// ── Listings ────────────────────────────────────────────────────

export interface ListingsParams {
  status?: ListingStatus;
  query_id?: number;
  q?: string;
  limit?: number;
  offset?: number;
}

export async function fetchListings(
  params: ListingsParams = {}
): Promise<{ total: number; data: Listing[] }> {
  const qs = new URLSearchParams();
  if (params.status)    qs.set("status",   params.status);
  if (params.query_id)  qs.set("query_id", String(params.query_id));
  if (params.q)         qs.set("q",        params.q);
  if (params.limit)     qs.set("limit",    String(params.limit));
  if (params.offset)    qs.set("offset",   String(params.offset));
  return apiFetch(`/listings?${qs}`);
}

export async function fetchHistory(
  mlbId: string
): Promise<{ mlb_id: string; history: PricePoint[] }> {
  return apiFetch(`/listings/${mlbId}/history`);
}

// ── Watchlist (search_queries) ──────────────────────────────────

export async function fetchWatchlist(): Promise<SearchQuery[]> {
  return apiFetch("/watchlist");
}

export async function createWatchlistTerm(termo: string): Promise<SearchQuery> {
  return apiFetch("/watchlist", {
    method: "POST",
    body: JSON.stringify({ termo }),
  });
}

export async function toggleWatchlistTerm(
  id: number,
  ativo: boolean
): Promise<SearchQuery> {
  return apiFetch(`/watchlist/${id}`, {
    method: "PUT",
    body: JSON.stringify({ ativo }),
  });
}

export async function deleteWatchlistTerm(id: number): Promise<void> {
  await apiFetch(`/watchlist/${id}`, { method: "DELETE" });
}

// ── Stats ───────────────────────────────────────────────────────

export async function fetchStats(): Promise<Stats> {
  return apiFetch("/stats");
}

// ── Formatação (igual ao mock-data.ts original) ─────────────────

export function formatPrice(v: number | null | undefined): string {
  if (v == null) return "—";
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
    maximumFractionDigits: 0,
  }).format(v);
}
