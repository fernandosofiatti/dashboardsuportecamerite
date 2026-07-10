"""
Conexão com o banco Supabase (Postgres) - armazena os tickets do Movidesk.
=============================================================================

Este módulo é usado tanto pelo extrai_movidesk.py (para gravar os tickets)
quanto pelo dashboard.py (para ler os tickets já salvos).

Usa o "Session pooler" do Supabase, que funciona em qualquer rede (a conexão
direta do Supabase costuma exigir IPv6, que muitas redes residenciais/de
empresa não têm).

SOBRE O DRIVER (pg8000, não psycopg2)
----------------------------------------
Usamos o driver pg8000 (100% Python) em vez de psycopg2-binary. O psycopg2
tem um bug conhecido que causa "Segmentation fault" em alguns ambientes de
nuvem (conflito de inicialização de SSL entre o módulo ssl do Python e a
libpq empacotada no psycopg2-binary) - isso derrubava o app no Streamlit
Community Cloud. O pg8000 não tem esse problema por não depender de
bibliotecas C nativas.

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
from sqlalchemy import create_engine, text

_RAW_SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL")

# Alias público (sem o driver pg8000 embutido) - só para exibição/diagnóstico
# em scripts como o testar_conexao.py.
SUPABASE_DB_URL = _RAW_SUPABASE_DB_URL

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
    if not _RAW_SUPABASE_DB_URL:
        raise RuntimeError(
            "SUPABASE_DB_URL não configurada. Defina essa variável de ambiente "
            "(localmente via .streamlit/secrets.toml, ou em produção nos "
            "Secrets do Streamlit Community Cloud) antes de rodar."
        )


def _url_com_driver_pg8000(url: str) -> str:
    """Reescreve a connection string para usar explicitamente o driver
    pg8000 (postgresql+pg8000://...), independente de como o usuário
    colou a URL original (postgresql:// ou postgres://)."""
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+pg8000://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+pg8000://" + url[len("postgres://"):]
    return url


def get_engine():
    """Engine SQLAlchemy (driver pg8000), compartilhado por leitura e escrita."""
    global _engine
    if _engine is None:
        _checar_config()
        _engine = create_engine(_url_com_driver_pg8000(_RAW_SUPABASE_DB_URL), pool_pre_ping=True)
    return _engine


def ensure_table():
    cols_sql = ",\n    ".join(f'"{name}" {tipo}' for name, tipo in COLUMNS)
    create_sql = f'CREATE TABLE IF NOT EXISTS {TABLE_NAME} (\n    {cols_sql}\n);'
    with get_engine().begin() as conn:
        conn.execute(text(create_sql))


def _to_pyval(v):
    """Converte valores do pandas/numpy para tipos nativos do Python,
    que é o que o driver do banco sabe gravar no Postgres."""
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
        {col: _to_pyval(v) for col, v in zip(col_names, row)}
        for row in df.itertuples(index=False, name=None)
    ]

    col_list = ", ".join(f'"{c}"' for c in col_names)
    placeholders = ", ".join(f":{c}" for c in col_names)
    update_cols = [c for c in col_names if c != "id"]
    update_clause = ", ".join(f'"{c}"=EXCLUDED."{c}"' for c in update_cols)

    sql = text(
        f'INSERT INTO {TABLE_NAME} ({col_list}) VALUES ({placeholders}) '
        f'ON CONFLICT (id) DO UPDATE SET {update_clause}'
    )

    with get_engine().begin() as conn:
        conn.execute(sql, records)

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
        with get_engine().connect() as conn:
            return conn.execute(text(f"SELECT count(*) FROM {TABLE_NAME}")).scalar()
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
        with get_engine().connect() as conn:
            row = conn.execute(text(f'SELECT MAX("ultima_atualizacao") FROM {TABLE_NAME}')).fetchone()
            return row[0] if row else None
    except Exception as exc:
        print(f"[db] Aviso ao consultar última sincronização: {exc}")
        return None
