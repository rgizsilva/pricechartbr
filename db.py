"""
db.py — Conexão centralizada com o PostgreSQL (Render).
Importado por ml_coletar.py e ml_monitorar.py.

Configure via variável de ambiente:
  export DATABASE_URL="postgresql://user:pass@host:5432/dbname"

Ou crie um arquivo .env na raiz com:
  DATABASE_URL=postgresql://user:pass@host:5432/dbname
"""
import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv()

_DATABASE_URL = os.environ.get("DATABASE_URL")

if not _DATABASE_URL:
    raise EnvironmentError(
        "Variável DATABASE_URL não definida. "
        "Crie um .env ou exporte a variável antes de rodar."
    )


def get_conn():
    """Retorna uma conexão psycopg2. Quem chama é responsável pelo .close()."""
    return psycopg2.connect(_DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


@contextmanager
def transaction():
    """Context manager: abre conexão + cursor, faz commit, fecha tudo."""
    conn = get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                yield cur
    finally:
        conn.close()
