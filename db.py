"""
Conexão com o banco Supabase (Postgres) - armazena os tickets do Movidesk.
=============================================================================

Este módulo é usado tanto pelo extrai_movidesk.py (para gravar os tickets)
quanto pelo dashboard.py (para ler os tickets já salvos).

Usa o "Session pooler" do Supabase, que funciona em qualquer rede (a conexão
direta do Supabase costuma exigir IPv6, que muitas redes residenciais/de
empresa não têm).

CONFIGURAÇÃO DA SENHA (IMPORTANTE)
------------------------------------
A connection string NÃO fica mais escrita no código (isso é necessário para
publicar este projeto no GitHub/Streamlit Cloud sem vazar a senha do banco).
Configure a variável de ambiente SUPABASE_DB_URL antes de rodar:

- Localmente: crie um arquivo .streamlit/secrets.toml (veja
  .streamlit/secrets.toml.example) ou exporte a variável de ambiente.
- No Streamlit Community Cloud: configure em "Settings > Secrets" do app -
  o Streamlit expõe os secrets automaticamente como variáveis de ambiente
  também, então este código funciona sem mudanças.
"""

import os

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from sqlalchemy import create_engine

SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL")

TABLE_NAME = "movidesk_tickets"

# Colunas geradas pelo extrai_movidesk.py (flatten_tickets), na ordem em que
# aparecem no DataFrame. Mantenha isso sincronizado com aquele arquivo.
COLUMNS = [
    ("id", "text PRIMARY KEY"),
    ("protocolo", "text"),
    ("assunto", "text"),
    ("categoria", "text"),
    ("urgencia", "text"),
    ("status", "text"),
    ("status_base", "text"),
    ("justificativa", "text"),
    ("origem", "integer"),
    ("servico_nivel1", "text"),
    ("servico_nivel2", "text"),
    ("servico_nivel3", "text"),
    ("tags", "text"),
    ("responsavel", "text"),
    ("equipe_responsavel", "text"),
    ("criado_por", "text"),
    ("cliente", "text"),
    ("data_abertura", "timestamp"),
    ("data_resolucao", "timestamp"),
    ("data_fechamento", "timestamp"),
    ("data_reabertura", "timestamp"),
    ("ultima_acao", "timestamp"),
    ("ultima_atualizacao", "timestamp"),
    ("qtd_acoes", "integer"),
    ("tempo_vida_horas_uteis_min", "integer"),
    ("tempo_parado_min", "integer"),
    ("resolvido_primeiro_atendimento", "boolean"),
    ("sla_contrato", "text"),
    ("sla_tempo_solucao_min", "integer"),
    ("sla_tempo_resposta_min", "integer"),
    ("tempo_ate_resolucao_horas", "double precision"),
    ("tempo_ate_fechamento_horas", "double precision"),
]

_engine = None


def _checar_config():
    if not SUPABASE_DB_URL:
        raise RuntimeError(
            "SUPABASE_DB_URL não configurada. Defina essa variável de ambiente "
            "(localmente via .streamlit/secrets.toml, ou em produção nos "
            "Secrets do Streamlit Community Cloud) antes de rodar."
        )


def get_engine():
    """Engine SQLAlchemy, usado só para leitura (pd.read_sql_query)."""
    global _engine
    if _engine is None:
        _checar_config()
        _engine = create_engine(SUPABASE_DB_URL, pool_pre_ping=True)
    return _engine


def get_connection():
    """Conexão psycopg2 "crua", usada para criar tabela e gravar dados."""
    _checar_config()
    return psycopg2.connect(SUPABASE_DB_URL)


def ensure_table():
    cols_sql = ",\n    ".join(f'"{name}" {tipo}' for name, tipo in COLUMNS)
    create_sql = f'CREATE TABLE IF NOT EXISTS {TABLE_NAME} (\n    {cols_sql}\n);'
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(create_sql)
        conn.commit()


def _to_pyval(v):
    """Converte valores do pandas/numpy para tipos nativos do Python,
    que é o que o psycopg2 sabe gravar no Postgres."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if hasattr(v, "item"):  # numpy int64/float64/bool_ etc.
        return v.item()
    return v


def upsert_tickets(df: pd.DataFrame) -> int:
    """Insere/atualiza os tickets no Supabase (upsert pelo campo id).
    Retorna a quantidade de linhas enviadas."""
    if df is None or df.empty:
        return 0

    ensure_table()

    col_names = [name for name, _ in COLUMNS if name in df.columns]
    df = df[col_names]

    records = [
        tuple(_to_pyval(v) for v in row)
        for row in df.itertuples(index=False, name=None)
    ]

    col_list = ", ".join(f'"{c}"' for c in col_names)
    update_cols = [c for c in col_names if c != "id"]
    update_clause = ", ".join(f'"{c}"=EXCLUDED."{c}"' for c in update_cols)

    sql = (
        f'INSERT INTO {TABLE_NAME} ({col_list}) VALUES %s '
        f'ON CONFLICT (id) DO UPDATE SET {update_clause}'
    )

    with get_connection() as conn:
        with conn.cursor() as cur:
            execute_values(cur, sql, records, page_size=500)
        conn.commit()

    return len(records)


def read_tickets() -> pd.DataFrame:
    """Lê todos os tickets salvos no Supabase. Retorna DataFrame vazio se
    a tabela ainda não existir."""
    try:
        engine = get_engine()
        return pd.read_sql_query(f"SELECT * FROM {TABLE_NAME} ORDER BY id", engine)
    except Exception as exc:  # tabela não existe ainda, ou erro de conexão
        print(f"[db] Aviso ao ler tickets: {exc}")
        return pd.DataFrame(columns=[name for name, _ in COLUMNS])


def count_tickets() -> int:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT count(*) FROM {TABLE_NAME}")
                return cur.fetchone()[0]
    except Exception as exc:
        print(f"[db] Aviso ao contar tickets: {exc}")
        return 0


def get_last_sync():
    """Retorna o maior valor de 'ultima_atualizacao' já salvo no Supabase
    (um datetime "naive" que representa um horário UTC), ou None se a
    tabela ainda não existir ou estiver vazia.

    Usado para fazer atualizações incrementais: em vez de buscar todo o
    histórico de novo, só buscamos tickets alterados depois desse horário.

    IMPORTANTE: se der erro de CONEXÃO (rede, senha errada, etc.), isso é
    impresso no console mas a função retorna None mesmo assim - o que faz
    o script cair na carga completa. Ou seja: um problema de conexão aqui
    não trava o script, mas o upsert_tickets() logo em seguida vai falhar
    "pra valer" (com traceback) se a conexão realmente estiver com problema.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f'SELECT MAX("ultima_atualizacao") FROM {TABLE_NAME}')
                row = cur.fetchone()
                return row[0] if row else None
    except Exception as exc:
        print(f"[db] Aviso ao consultar última sincronização: {exc}")
        return None
