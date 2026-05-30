-- =============================================================
-- Price Compass — Schema PostgreSQL (Render)
-- =============================================================
-- Roda uma vez para criar as tabelas.
-- Usa ON CONFLICT para ser idempotente (pode rodar várias vezes).
-- =============================================================

-- Termos de busca que o scraper vai monitorar.
-- Substituiu o campo hardcoded PRODUTO = "star wars..." nos scripts.
CREATE TABLE IF NOT EXISTS search_queries (
    id          SERIAL PRIMARY KEY,
    termo       TEXT        NOT NULL UNIQUE,
    ativo       BOOLEAN     NOT NULL DEFAULT TRUE,
    ultima_busca TIMESTAMPTZ,
    criado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Anúncios individuais capturados no Mercado Livre.
-- Equivale ao watchlist.txt, mas sem duplicatas e com upsert.
CREATE TABLE IF NOT EXISTS listings (
    mlb_id          TEXT        PRIMARY KEY,            -- ex: MLB123456789
    query_id        INTEGER     REFERENCES search_queries(id) ON DELETE SET NULL,
    titulo          TEXT        NOT NULL,
    url             TEXT        NOT NULL,
    condicao        TEXT,                               -- "Novo", "Usado", etc.
    status          TEXT        NOT NULL DEFAULT 'active', -- 'active' | 'closed'
    preco_inicial   NUMERIC(12, 2),
    preco_final     NUMERIC(12, 2),
    finalizado_em   TIMESTAMPTZ,
    capturado_em    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Histórico de preços — cada evento de fechamento ou verificação vira uma linha.
-- Não apaga linhas antigas: é a fonte de verdade para os gráficos.
CREATE TABLE IF NOT EXISTS price_history (
    id          BIGSERIAL   PRIMARY KEY,
    mlb_id      TEXT        NOT NULL REFERENCES listings(mlb_id) ON DELETE CASCADE,
    preco       NUMERIC(12, 2) NOT NULL,
    evento      TEXT        NOT NULL DEFAULT 'sold',   -- 'sold' | 'check' | 'manual'
    condicao    TEXT,
    fonte       TEXT        DEFAULT 'mercadolivre',
    registrado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índices para as queries mais comuns do frontend
CREATE INDEX IF NOT EXISTS idx_listings_status     ON listings(status);
CREATE INDEX IF NOT EXISTS idx_listings_query_id   ON listings(query_id);
CREATE INDEX IF NOT EXISTS idx_listings_atualizado ON listings(atualizado_em DESC);
CREATE INDEX IF NOT EXISTS idx_history_mlb_id      ON price_history(mlb_id);
CREATE INDEX IF NOT EXISTS idx_history_registrado  ON price_history(registrado_em DESC);

-- Insere termo de exemplo (remova ou edite conforme seu uso)
INSERT INTO search_queries (termo)
VALUES ('star wars knights of the old republic')
ON CONFLICT (termo) DO NOTHING;
