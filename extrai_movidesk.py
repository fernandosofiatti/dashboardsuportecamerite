"""
Extração de tickets do Movidesk via API -> Supabase (+ backup em Excel)
=========================================================================

O QUE ESTE SCRIPT FAZ
----------------------
1. Autentica na API pública do Movidesk usando um Token.
2. Na PRIMEIRA vez (Supabase ainda vazio), busca TODO o histórico de
   tickets, combinando:
   - /tickets/past  -> histórico completo (posição D-1)
   - /tickets       -> tickets atualizados nas últimas horas/dias (dados "quentes")
   Isso é a carga inicial e pode demorar bastante se houver muitos tickets
   (o Movidesk limita 10 requisições por minuto).
3. Nas vezes seguintes, faz uma ATUALIZAÇÃO INCREMENTAL: busca só os
   tickets alterados desde a última sincronização (usando $filter na API).
   Isso é bem mais rápido, geralmente só 1-2 requisições.
4. Achata campos aninhados (responsável, cliente, criador do ticket).
5. Calcula algumas métricas úteis para o BI (tempo até resolução, até fechamento etc).
6. Grava tudo no banco Supabase (upsert por id, via db.py) - é essa a fonte
   que o dashboard.py usa.
7. Também atualiza uma cópia local em .xlsx como backup/uso avulso (Power BI,
   Excel etc.), sempre com a base completa (não só o que mudou agora).

COMO USAR
---------
1. Pegue seu Token em: Movidesk > Configurações > Conta > Parâmetros > aba "Ambiente"
   (role até o final da página).
2. Configure o token abaixo (linha MOVIDESK_TOKEN) ou defina a variável de
   ambiente MOVIDESK_TOKEN antes de rodar o script.
3. Instale as dependências:
       pip install -r requirements.txt
4. Rode:
       python extrai_movidesk.py

   Para uma carga RÁPIDA e limitada (só tickets criados nos últimos N
   dias - útil pra não esperar o histórico inteiro), rode:
       python extrai_movidesk.py --days 30

   Para forçar uma carga completa de novo (ignorando o que já está no
   Supabase), rode:
       python extrai_movidesk.py --full

LIMITES DA API (importante)
----------------------------
- Máximo de 10 requisições por minuto (o script já respeita isso).
- 3 erros seguidos = bloqueio de 60s (depois 120s, depois 300s se persistir).
- /tickets só traz tickets com "lastUpdate" de até ~90 dias atrás.
- /tickets/past traz o histórico completo, mas com defasagem de 1 dia (D-1).
  Por isso a carga inicial busca dos dois endpoints e remove duplicados,
  ficando sempre com a versão mais recente (maior lastUpdate) de cada ticket.

ATENÇÃO SOBRE O TOKEN
----------------------
O token de acesso ao Movidesk NÃO fica mais escrito neste arquivo (isso é
necessário para publicar este projeto no GitHub/Streamlit Cloud sem vazar
credenciais). Configure a variável de ambiente MOVIDESK_TOKEN antes de rodar:

- Localmente: crie um arquivo .streamlit/secrets.toml (veja
  .streamlit/secrets.toml.example) ou exporte a variável de ambiente.
- No Streamlit Community Cloud: configure em "Settings > Secrets" do app -
  o Streamlit expõe os secrets automaticamente como variáveis de ambiente
  também, então este código funciona sem mudanças.
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
import pandas as pd

import db

# --------------------------------------------------------------------------
# CONFIGURAÇÃO
# --------------------------------------------------------------------------

MOVIDESK_TOKEN = os.environ.get("MOVIDESK_TOKEN")

BASE_URL = "https://api.movidesk.com/public/v1"

OUTPUT_FILE = "movidesk_tickets.xlsx"

# Respeitando o limite de 10 req/min (1 a cada 6s deixa uma margem de segurança)
SECONDS_BETWEEN_REQUESTS = 6.5

# Quantos tickets pedir por página (o Movidesk aceita valores como este)
PAGE_SIZE = 200

# Campos que serão trazidos da API (evita payloads gigantes e desnecessários).
# Ajuste essa lista conforme os campos que você quiser no seu BI.
SELECT_FIELDS = [
    "id",
    "protocol",
    "type",
    "subject",
    "category",
    "urgency",
    "status",
    "baseStatus",
    "justification",
    "origin",
    "createdDate",
    "owner",
    "ownerTeam",
    "createdBy",
    "serviceFirstLevel",
    "serviceSecondLevel",
    "serviceThirdLevel",
    "tags",
    "resolvedIn",
    "reopenedIn",
    "closedIn",
    "lastActionDate",
    "actionCount",
    "lastUpdate",
    "lifetimeWorkingTime",
    "stoppedTime",
    "resolvedInFirstCall",
    "slaAgreement",
    "slaSolutionTime",
    "slaResponseTime",
    "clients",
]


# --------------------------------------------------------------------------
# FUNÇÕES DE ACESSO À API
# --------------------------------------------------------------------------

def _sleep_rate_limit():
    time.sleep(SECONDS_BETWEEN_REQUESTS)


def api_get(endpoint: str, params: dict) -> list:
    """
    Faz um GET na API do Movidesk, tratando o limite de requisições (429)
    de forma automática usando o header 'retry-after'.
    """
    url = f"{BASE_URL}{endpoint}"
    params = {**params, "token": MOVIDESK_TOKEN}

    for attempt in range(5):
        response = requests.get(url, params=params, timeout=60)

        if response.status_code == 200:
            return response.json()

        if response.status_code == 429:
            retry_after = int(response.headers.get("retry-after", 60))
            print(f"  [!] Limite de requisições atingido. Aguardando {retry_after}s...")
            time.sleep(retry_after + 1)
            continue

        # Outros erros: mostra e aborta essa página
        print(f"  [!] Erro {response.status_code} em {endpoint}: {response.text[:300]}")
        response.raise_for_status()

    raise RuntimeError(f"Falha ao consultar {endpoint} após múltiplas tentativas.")


def fetch_all_tickets(endpoint: str, filter_expr: str = None) -> list:
    """
    Pagina um endpoint de tickets (/tickets ou /tickets/past) até não
    haver mais registros, respeitando o limite de requisições por minuto.

    Se filter_expr for informado, é enviado como $filter (sintaxe OData),
    por exemplo: "lastUpdate gt 2026-07-01T00:00:00.00z"
    """
    all_tickets = []
    skip = 0

    while True:
        params = {
            "$select": ",".join(SELECT_FIELDS),
            "$top": PAGE_SIZE,
            "$skip": skip,
            "$orderby": "id",
        }
        if filter_expr:
            params["$filter"] = filter_expr

        print(f"  Buscando {endpoint}  (skip={skip})...")
        page = api_get(endpoint, params)

        if not page:
            break

        all_tickets.extend(page)
        skip += PAGE_SIZE

        if len(page) < PAGE_SIZE:
            break

        _sleep_rate_limit()

    return all_tickets


# --------------------------------------------------------------------------
# TRANSFORMAÇÃO DOS DADOS
# --------------------------------------------------------------------------

def _person_name(person: dict) -> str:
    if not isinstance(person, dict):
        return None
    return person.get("businessName") or person.get("personName") or person.get("email")


def _organization_name(person: dict) -> str:
    """Nome da organização/empresa vinculada a uma pessoa (solicitante),
    quando cadastrada no Movidesk - vem como um sub-objeto "organization"
    dentro do Person/Requester (ex.: clients[0]["organization"])."""
    if not isinstance(person, dict):
        return None
    org = person.get("organization")
    return _person_name(org) if isinstance(org, dict) else None


def _cliente_do_ticket(t: dict) -> str:
    """Determina o "cliente" (empresa) do ticket.

    Nossa conta do Movidesk não usa formalmente o campo "clients" (lista de
    solicitantes) com organização vinculada em todo ticket, então tentamos
    nessa ordem, usando o primeiro que existir:
      1. Organização do primeiro solicitante em "clients"
         (clients[0]["organization"])
      2. Organização de quem abriu o ticket ("createdBy")
      3. Nome do primeiro solicitante em "clients" (pessoa, sem organização)

    Se mesmo assim ficar tudo vazio, o próximo passo é rodar
    dump_ticket_bruto.py (veja abaixo) pra inspecionar o JSON cru de alguns
    tickets reais e confirmar como a conta do Movidesk está estruturada."""
    clients = t.get("clients")
    primeiro_cliente = clients[0] if isinstance(clients, list) and clients else None

    org = _organization_name(primeiro_cliente) or _organization_name(t.get("createdBy"))
    if org:
        return org

    return _person_name(primeiro_cliente) if primeiro_cliente else None


def flatten_tickets(raw_tickets: list) -> pd.DataFrame:
    rows = []
    for t in raw_tickets:
        rows.append({
            "id": t.get("id"),
            "protocolo": t.get("protocol"),
            "assunto": t.get("subject"),
            "categoria": t.get("category"),
            "urgencia": t.get("urgency"),
            "status": t.get("status"),
            "status_base": t.get("baseStatus"),
            "justificativa": t.get("justification"),
            "origem": t.get("origin"),
            "servico_nivel1": t.get("serviceFirstLevel"),
            "servico_nivel2": t.get("serviceSecondLevel"),
            "servico_nivel3": t.get("serviceThirdLevel"),
            "tags": ", ".join(t.get("tags") or []),
            "responsavel": _person_name(t.get("owner")),
            "equipe_responsavel": t.get("ownerTeam"),
            "criado_por": _person_name(t.get("createdBy")),
            "cliente": _cliente_do_ticket(t),
            "data_abertura": t.get("createdDate"),
            "data_resolucao": t.get("resolvedIn"),
            "data_fechamento": t.get("closedIn"),
            "data_reabertura": t.get("reopenedIn"),
            "ultima_acao": t.get("lastActionDate"),
            "ultima_atualizacao": t.get("lastUpdate"),
            "qtd_acoes": t.get("actionCount"),
            "tempo_vida_horas_uteis_min": t.get("lifetimeWorkingTime"),
            "tempo_parado_min": t.get("stoppedTime"),
            "resolvido_primeiro_atendimento": t.get("resolvedInFirstCall"),
            "sla_contrato": t.get("slaAgreement"),
            "sla_tempo_solucao_min": t.get("slaSolutionTime"),
            "sla_tempo_resposta_min": t.get("slaResponseTime"),
        })

    df = pd.DataFrame(rows)

    # Converte colunas de data para datetime
    date_cols = [
        "data_abertura", "data_resolucao", "data_fechamento",
        "data_reabertura", "ultima_acao", "ultima_atualizacao",
    ]
    for col in date_cols:
        df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)

    # Métricas derivadas úteis para o BI
    df["tempo_ate_resolucao_horas"] = (
        (df["data_resolucao"] - df["data_abertura"]).dt.total_seconds() / 3600
    )
    df["tempo_ate_fechamento_horas"] = (
        (df["data_fechamento"] - df["data_abertura"]).dt.total_seconds() / 3600
    )

    # O Excel não aceita datetimes "timezone-aware" -> removemos o timezone
    # (os valores continuam em UTC, só perdem a marcação explícita)
    for col in date_cols:
        df[col] = df[col].dt.tz_localize(None)

    return df


# --------------------------------------------------------------------------
# EXECUÇÃO PRINCIPAL
# --------------------------------------------------------------------------

def _dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """Remove tickets duplicados (mesmo id), mantendo a versão com
    'ultima_atualizacao' mais recente."""
    df = df.copy()
    df["ultima_atualizacao_sort"] = df["ultima_atualizacao"]
    return (
        df.sort_values("ultima_atualizacao_sort")
        .drop_duplicates(subset="id", keep="last")
        .drop(columns="ultima_atualizacao_sort")
        .sort_values("id")
        .reset_index(drop=True)
    )


def run_extraction(full: bool = False, days: int = None) -> pd.DataFrame:
    """
    Busca os tickets do Movidesk e grava no Supabase.

    - Se days for informado (ex: days=30): carga RÁPIDA e limitada, busca só
      tickets CRIADOS nos últimos N dias (usa só /tickets, sem /tickets/past
      - por isso só funciona para períodos de até ~90 dias). Ideal pra ter
      uma base útil rapidinho sem esperar o histórico inteiro.
    - Se full=True, OU se o Supabase ainda estiver vazio (e days não foi
      informado): faz a carga completa (todo o histórico via /tickets/past
      + /tickets). Demora mais, principalmente com muitos tickets.
    - Caso contrário: faz uma atualização incremental, buscando só os
      tickets alterados desde a última sincronização. Bem mais rápido.

    Retorna o DataFrame com os tickets buscados NESTA rodada (não é a base
    inteira quando a atualização é incremental/parcial).
    """
    if MOVIDESK_TOKEN in (None, "", "COLE_SEU_TOKEN_AQUI"):
        raise RuntimeError(
            "Configure a variável de ambiente MOVIDESK_TOKEN antes de rodar "
            "(veja .streamlit/secrets.toml.example, ou os Secrets do app no "
            "Streamlit Community Cloud)."
        )

    if days is not None:
        since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        filtro = f"createdDate gt {since.strftime('%Y-%m-%dT%H:%M:%S.00z')}"
        print(f"Carga rápida: buscando tickets criados nos últimos {days} dias "
              f"(desde {since.isoformat()} UTC)...")
        all_raw = fetch_all_tickets("/tickets", filter_expr=filtro)
        print(f"  -> {len(all_raw)} tickets encontrados.")
    else:
        last_sync = None if full else db.get_last_sync()

        if last_sync is None:
            print("Carga completa: buscando todo o histórico (pode demorar bastante "
                  "se houver muitos tickets - o Movidesk limita 10 requisições/minuto).")

            print("\n[1/2] Buscando histórico completo (/tickets/past)...")
            past_tickets = fetch_all_tickets("/tickets/past")
            print(f"  -> {len(past_tickets)} tickets encontrados no histórico.")

            _sleep_rate_limit()

            print("\n[2/2] Buscando tickets recentes (/tickets)...")
            recent_tickets = fetch_all_tickets("/tickets")
            print(f"  -> {len(recent_tickets)} tickets encontrados recentes.")

            all_raw = past_tickets + recent_tickets
        else:
            # Margem de segurança de 1h para não perder tickets no limite exato
            since = last_sync - timedelta(hours=1)
            filtro = f"lastUpdate gt {since.strftime('%Y-%m-%dT%H:%M:%S.00z')}"
            print(f"Atualização incremental: buscando tickets alterados desde {since.isoformat()} UTC...")
            all_raw = fetch_all_tickets("/tickets", filter_expr=filtro)
            print(f"  -> {len(all_raw)} tickets novos/alterados encontrados.")

    if not all_raw:
        print("\nNenhum ticket novo ou alterado. Base do Supabase já está em dia.")
        return pd.DataFrame()

    df = _dedupe(flatten_tickets(all_raw))
    print(f"\nTotal de tickets únicos nesta rodada: {len(df)}")

    print("\nEnviando para o Supabase...")
    enviados = db.upsert_tickets(df)
    print(f"  -> {enviados} tickets gravados/atualizados no Supabase.")

    return df


def export_excel_backup():
    """Exporta um backup local sempre com a base COMPLETA (lida do
    Supabase), não só o que foi alterado na última rodada."""
    df_completo = db.read_tickets()
    if df_completo.empty:
        return

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        df_completo.to_excel(writer, sheet_name="tickets", index=False)
        worksheet = writer.sheets["tickets"]
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions

    print(f"Backup local salvo em: {os.path.abspath(OUTPUT_FILE)}")


def _parse_days_arg():
    """Lê '--days N' da linha de comando, se informado."""
    if "--days" not in sys.argv:
        return None
    idx = sys.argv.index("--days")
    try:
        return int(sys.argv[idx + 1])
    except (IndexError, ValueError):
        print("ERRO: use '--days' seguido de um número, ex: --days 30")
        sys.exit(1)


def main():
    full = "--full" in sys.argv
    days = _parse_days_arg()

    print("Iniciando extração de tickets do Movidesk...")
    print(f"Início: {datetime.now(timezone.utc).isoformat()}")

    run_extraction(full=full, days=days)
    export_excel_backup()

    print("\nPronto! Os dados já estão no Supabase - é só abrir o dashboard.")


if __name__ == "__main__":
    main()
