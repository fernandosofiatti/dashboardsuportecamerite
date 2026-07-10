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
from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    MetaData,
    Table,
    TIMESTAMP,
    Text,
    create_engine,
    text,
)
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION
from sqlalchemy.dialects.postgresql import insert as pg_insert

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

# Mapeia os tipos SQL (strings usadas no CREATE TABLE) para tipos do
# SQLAlchemy Core. Isso é usado para montar um Table() tipado - com isso,
# o SQLAlchemy manda o tipo de cada parâmetro para o driver (pg8000), em vez
# de mandar um valor "cru" e deixar o Postgres tentar adivinhar o tipo.
#
# Sem isso, um upsert em lote onde uma coluna vem como None (NULL) em algum
# registro pode disparar "ProgrammingError: could not determine data type
# of parameter" no Postgres, porque o pg8000 não sabe dizer se aquele NULL
# é texto, número, data etc.
_SQL_TYPE_MAP = {
    "text": Text,
    "integer": Integer,
    "boolean": Boolean,
    "timestamp": TIMESTAMP,
    "double precision": DOUBLE_PRECISION,
}

_metadata = MetaData()
_table = None

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


def get_table() -> Table:
    """Monta (uma única vez) o objeto Table do SQLAlchemy, com o tipo de
    cada coluna - usado tanto para criar a tabela quanto para montar o
    upsert com os tipos corretos."""
    global _table
    if _table is None:
        colunas = []
        for name, tipo_sql in COLUMNS:
            eh_pk = "PRIMARY KEY" in tipo_sql
            tipo_base = tipo_sql.replace("PRIMARY KEY", "").strip()
            colunas.append(Column(name, _SQL_TYPE_MAP[tipo_base], primary_key=eh_pk))
        _table = Table(TABLE_NAME, _metadata, *colunas)
    return _table


def ensure_table():
    _metadata.create_all(get_engine(), tables=[get_table()], checkfirst=True)


# Nome da coluna -> tipo SQL "base" (sem o "PRIMARY KEY"), para saber quando
# um valor precisa ser convertido para inteiro antes de gravar.
_TIPO_POR_COLUNA = {
    name: tipo.replace("PRIMARY KEY", "").strip() for name, tipo in COLUMNS
}


def _to_pyval(v, coluna: str = None):
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
        v = v.item()

    # Colunas com dados faltantes viram float64 no pandas (ex.: 40.0 em vez
    # de 40) mesmo sendo conceitualmente inteiras. O Postgres não aceita
    # ponto decimal em coluna "integer" (erro: invalid input syntax for
    # type integer: "40.0") - então arredondamos para int nesse caso.
    if coluna is not None and _TIPO_POR_COLUNA.get(coluna) == "integer" and isinstance(v, float):
        v = int(round(v))

    return v


def upsert_tickets(df: pd.DataFrame) -> int:
    """Insere/atualiza os tickets no Supabase (upsert pelo campo id).
    Retorna a quantidade de linhas enviadas.

    Usa o construtor de INSERT do SQLAlchemy (em vez de SQL "cru" em texto)
    justamente para que cada parâmetro vá tipado - isso evita o erro do
    Postgres "could not determine data type of parameter" que acontecia
    quando uma coluna vinha None (NULL) em algum ticket do lote."""
    if df is None or df.empty:
        return 0

    ensure_table()
    table = get_table()

    col_names = [name for name, _ in COLUMNS if name in df.columns]
    df = df[col_names]

    # Um único INSERT com várias linhas + ON CONFLICT falha com
    # "ON CONFLICT DO UPDATE command cannot affect row a second time" se o
    # MESMO id aparecer duas vezes dentro do próprio lote (pode acontecer se
    # a extração do Movidesk trouxer o mesmo ticket em duas páginas, por
    # exemplo). Por isso removemos duplicatas de id no lote antes de gravar,
    # mantendo a última ocorrência (mais recente).
    if "id" in df.columns:
        df = df.drop_duplicates(subset=["id"], keep="last")

    records = [
        {col: _to_pyval(v, col) for col, v in zip(col_names, row)}
        for row in df.itertuples(index=False, name=None)
    ]

    update_cols = [c for c in col_names if c != "id"]

    # Grava em lotes para evitar um único INSERT gigantesco (e para que, se
    # algum lote específico falhar, os demais já gravados não sejam
    # descartados).
    TAMANHO_LOTE = 500
    total_gravado = 0
    with get_engine().begin() as conn:
        for inicio in range(0, len(records), TAMANHO_LOTE):
            lote = records[inicio:inicio + TAMANHO_LOTE]
            stmt = pg_insert(table).values(lote)
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={c: stmt.excluded[c] for c in update_cols},
            )
            conn.execute(stmt)
            total_gravado += len(lote)

    return total_gravado


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
