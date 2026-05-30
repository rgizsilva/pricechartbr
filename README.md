# Price Compass — Setup & Deploy

## Estrutura do projeto

```
price_compass_backend/
├── schema.sql          ← roda uma vez no Postgres do Render
├── db.py               ← conexão centralizada (usado pelos scripts)
├── ml_coletar.py       ← coleta anúncios do ML → banco
├── ml_monitorar.py     ← detecta vendas → banco
├── api.py              ← FastAPI exposta para o frontend
├── render.yaml         ← configuração de deploy automático no Render
├── requirements.txt
└── .env.example        ← copie para .env com suas credenciais

frontend_src/           ← coloque no src/ do seu projeto Loveable
├── lib/api.ts          ← camada de serviço (substitui mock-data)
└── routes/admin.tsx    ← Admin com CRUD real de termos
```

---

## 1. Banco de dados (Render Postgres — já criado)

Conecte com qualquer cliente (psql, TablePlus, DBeaver) usando a External URL e rode o schema:

```bash
psql "postgresql://admin:SUASENHA@dpg-xxxx.oregon-postgres.render.com/pricechart_7hkd" -f schema.sql
```

Ou via psql direto:
```bash
psql $DATABASE_URL -f schema.sql
```

---

## 2. Subir o projeto no GitHub

```bash
cd price_compass_backend

git init
git add .
git commit -m "feat: price compass backend inicial"

# Crie um repo no GitHub (ex: price-compass-backend) e conecte:
git remote add origin https://github.com/SEU_USUARIO/price-compass-backend.git
git branch -M main
git push -u origin main
```

---

## 3. Deploy do Backend no Render (Web Service)

1. Acesse https://render.com → **New → Web Service**
2. Conecte ao repositório GitHub que você acabou de criar
3. Configure:
   - **Name:** `price-compass-api`
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn api:app --host 0.0.0.0 --port $PORT`
4. Em **Environment Variables**, adicione:
   - `DATABASE_URL` = `postgresql://admin:n02MDMlpQm1Ecx3fm6KwT1eWjF51mRUF@dpg-d8dgnjkm0tmc73dubvi0-a.oregon-postgres.render.com/pricechart_7hkd`
5. Clique **Create Web Service**

> O Render vai fazer build e deploy automaticamente. Cada push no `main` dispara um novo deploy.

Após o deploy, sua API estará em:
```
https://price-compass-api.onrender.com
```

Teste acessando: `https://price-compass-api.onrender.com/health` — deve retornar `{"status":"ok"}`

Docs interativas: `https://price-compass-api.onrender.com/docs`

---

## 4. Rodar o schema no banco (uma vez)

Com psql instalado localmente:

```bash
psql "postgresql://admin:n02MDMlpQm1Ecx3fm6KwT1eWjF51mRUF@dpg-d8dgnjkm0tmc73dubvi0-a.oregon-postgres.render.com/pricechart_7hkd" -f schema.sql
```

Ou use TablePlus / DBeaver conectando com os dados:
- **Host:** `dpg-d8dgnjkm0tmc73dubvi0-a.oregon-postgres.render.com`
- **Port:** `5432`
- **Database:** `pricechart_7hkd`
- **User:** `admin`
- **Password:** `n02MDMlpQm1Ecx3fm6KwT1eWjF51mRUF`

---

## 5. Coletar anúncios (rodar localmente ou via Render Cron Job)

### Local (para testar):

```bash
cp .env.example .env
# edite .env e coloque sua DATABASE_URL

pip install -r requirements.txt

# Coleta todos os termos ativos
python ml_coletar.py

# Coleta um termo específico (teste)
python ml_coletar.py --termo "star wars n64"
```

### Cron Job no Render:

1. No Render → **New → Cron Job**
2. Conecte o mesmo repositório
3. Configure:
   - **Command:** `python ml_coletar.py`
   - **Schedule:** `0 6 * * *` (todo dia às 6h)
4. Adicione a mesma `DATABASE_URL` nas env vars

Repita para o monitorador:
- **Command:** `python ml_monitorar.py --uma-vez`
- **Schedule:** `*/5 * * * *` (a cada 5 minutos)

---

## 6. Frontend Loveable

1. Copie `frontend_src/lib/api.ts` → `src/lib/api.ts`
2. Copie `frontend_src/routes/admin.tsx` → `src/routes/admin.tsx`
3. No Loveable, defina a variável de ambiente:
   ```
   VITE_API_URL=https://price-compass-api.onrender.com
   ```
4. Em outros arquivos que importam de `@/lib/mock-data`, substitua pelas funções equivalentes de `@/lib/api.ts`.

---

## Endpoints disponíveis

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/health` | Health check |
| GET | `/listings` | Lista anúncios (filtros: status, q, query_id) |
| GET | `/listings/{id}/history` | Histórico de preços |
| GET | `/watchlist` | Termos monitorados |
| POST | `/watchlist` | Adiciona termo `{"termo": "..."}` |
| PUT | `/watchlist/{id}` | Ativa/pausa `{"ativo": true}` |
| DELETE | `/watchlist/{id}` | Remove termo |
| GET | `/stats` | Resumo para dashboard |

---

## Fluxo de dados

```
ML (scraper) → listings + price_history (Postgres/Render)
                       ↕
               FastAPI (/listings, /stats...)
                       ↕
            Loveable Frontend (React)
```
