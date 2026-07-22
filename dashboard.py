"""
Dashboard de Suporte Técnico - Movidesk
=========================================

App em Streamlit que lê os tickets do Supabase (gravados pelo
extrai_movidesk.py via db.py) e mostra KPIs e gráficos interativos,
organizados em abas: Visão Geral, Categorias & Serviços, Equipe,
Tempo & SLA, Canais e Detalhado.

Também tem controles na barra lateral para atualizar os dados direto da
API do Movidesk (grava no Supabase e atualiza um backup local em Excel),
sem precisar rodar o script de extração separadamente.

COMO USAR
---------
Normalmente você não roda este arquivo diretamente - use o
iniciar_dashboard.bat, que já cuida de instalar dependências e abrir
o navegador. Se quiser rodar manualmente:

    pip install -r requirements.txt
    streamlit run dashboard.py
"""

import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import extrai_movidesk as movidesk  # noqa: E402  (reaproveita a lógica de extração)
import db  # noqa: E402  (leitura/gravação no Supabase)

DATA_FILE = os.path.join(SCRIPT_DIR, movidesk.OUTPUT_FILE)

DATE_COLS = [
    "data_abertura", "data_resolucao", "data_fechamento",
    "data_reabertura", "ultima_acao", "ultima_atualizacao",
]

ORIGIN_LABELS = {
    1: "Via web (cliente)", 2: "Via web (agente)", 3: "E-mail", 4: "Gatilho do sistema",
    5: "Chat", 7: "E-mail (sistema)", 8: "Formulário de contato", 9: "Via API",
    10: "Agendamento automático", 11: "Jira", 12: "Redmine", 13: "Ligação recebida",
    14: "Ligação realizada", 15: "Ligação perdida", 16: "Chamada abandonada",
    18: "WhatsApp", 19: "Integração Movidesk", 20: "Zenvia Chat",
    21: "Não atendida", 22: "Facebook Messenger", 23: "WhatsApp Business",
    24: "Altu", 25: "WhatsApp Ativo",
}

# --------------------------------------------------------------------------
# IDENTIDADE VISUAL
# --------------------------------------------------------------------------

# Paleta extraída direto do site camerite.com (cores computadas dos botões,
# títulos e destaques da página, não são "chutadas").
COLOR_SEQUENCE = [
    "#7B48EA", "#33CCF0", "#14B8A6", "#F59E0B", "#EF4444",
    "#A785F1", "#EC4899", "#84CC16", "#0090D9", "#64748B",
]
COLOR_TEAL = "#33CCF0"
CAMERITE_ROXO = "#7B48EA"          # roxo principal (botões "Fale Conosco"/"Seja Franqueado")
CAMERITE_ROXO_ESCURO = "#29184E"   # roxo-marinho escuro (cor dos títulos do site)
CAMERITE_CIANO = "#33CCF0"         # ciano de destaque
CAMERITE_AZUL = "#0090D9"          # azul do botão secundário "Soluções"
CAMERITE_ESCURO = "#29184E"        # mesmo tom escuro, usado no fundo da sidebar

px.defaults.template = "plotly_white"
px.defaults.color_discrete_sequence = COLOR_SEQUENCE

MESES_PT_ABREV = [
    "", "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
]


def rotulo_semana(inicio: pd.Timestamp) -> str:
    """Formata o início de uma semana (segunda-feira) como "D a D mês",
    ex.: "6 a 12 jun" - mostra o intervalo de dias em vez de só uma data
    solta, que era difícil de interpretar no eixo/legenda dos gráficos
    semanais. Se a semana cruzar a virada do mês, mostra os dois:
    "29 mai a 4 jun"."""
    fim = inicio + pd.Timedelta(days=6)
    if inicio.month == fim.month:
        return f"{inicio.day} a {fim.day} {MESES_PT_ABREV[inicio.month]}"
    return f"{inicio.day} {MESES_PT_ABREV[inicio.month]} a {fim.day} {MESES_PT_ABREV[fim.month]}"

st.set_page_config(
    page_title="Dashboard de Suporte - Movidesk",
    page_icon="📊",
    layout="wide",
)

st.markdown(
    """
    <style>
    /* ------------------------------------------------------------------
       Visual inspirado no Qlik Sense: fundo neutro cinza-claro (em vez do
       roxo-claro anterior), cards brancos "achatados" com sombra sutil,
       KPIs com uma barra colorida no topo (como os cards "NET SALES",
       "QUANTITY" etc do Qlik) e títulos de seção em caixa alta.
       ------------------------------------------------------------------ */
    .stApp { background-color: #F4F5F7; }

    [data-testid="stSidebar"] {
        background-color: #29184E;
    }
    [data-testid="stSidebar"] * { color: #E4E7EC !important; }

    /* Os campos de entrada (número, data) têm fundo claro por padrão do
       Streamlit - sem isso, o texto digitado ficava cinza-claro em cima
       de um fundo branco, quase ilegível. */
    [data-testid="stSidebar"] input,
    [data-testid="stSidebar"] textarea {
        color: #29184E !important;
        background-color: #FFFFFF !important;
    }
    [data-testid="stSidebar"] svg { fill: #29184E; }

    /* Botões dos filtros (st.pills): deixamos sem cor forçada aqui de
       propósito - o botão "aceso" (selecionado) já usa a primaryColor do
       tema (definida em .streamlit/config.toml, a mesma roxa da marca),
       e o Streamlit já escolhe automaticamente uma cor de texto legível
       para cada estado. */

    [data-testid="stSidebar"] .stButton button {
        background-color: #7B48EA; color: white !important; border: none;
        font-weight: 600;
    }
    [data-testid="stSidebar"] .stButton button:hover { background-color: #5B32C4; }

    .app-header {
        padding: 1.25rem 1.5rem; margin-bottom: 1rem;
        background: linear-gradient(90deg, #29184E 0%, #7B48EA 100%);
        border-radius: 10px; color: white;
        box-shadow: 0 1px 3px rgba(16, 24, 40, 0.12);
    }
    .app-header h1 { margin: 0; font-size: 1.6rem; color: white; }
    .app-header p { margin: 0.25rem 0 0 0; color: #D3C2F8; font-size: 0.9rem; }

    /* Cards de KPI estilo Qlik: fundo branco, borda neutra fininha, sombra
       leve e uma faixa colorida no topo (troca de cor a cada card, igual
       aos cartões "NET SALES / QUANTITY / BASKET SIZE..." do Qlik Sense). */
    [data-testid="stMetric"] {
        background-color: white; border: 1px solid #E4E7EC;
        border-top: 4px solid #7B48EA;
        border-radius: 8px; padding: 1rem 1rem 0.75rem 1rem;
        box-shadow: 0 1px 3px rgba(16, 24, 40, 0.06);
    }
    [data-testid="stColumn"]:nth-of-type(6n+2) [data-testid="stMetric"] { border-top-color: #33CCF0; }
    [data-testid="stColumn"]:nth-of-type(6n+3) [data-testid="stMetric"] { border-top-color: #14B8A6; }
    [data-testid="stColumn"]:nth-of-type(6n+4) [data-testid="stMetric"] { border-top-color: #F59E0B; }
    [data-testid="stColumn"]:nth-of-type(6n+5) [data-testid="stMetric"] { border-top-color: #EF4444; }
    [data-testid="stColumn"]:nth-of-type(6n) [data-testid="stMetric"] { border-top-color: #0090D9; }

    [data-testid="stMetricLabel"] {
        font-weight: 700; color: #667085; text-transform: uppercase;
        font-size: 0.72rem; letter-spacing: 0.04em;
    }
    [data-testid="stMetricValue"] { font-weight: 700; color: #1D2939; }

    /* Títulos de seção (st.markdown("##### ...")) em caixa alta com uma
       linha fina embaixo - mesma linguagem visual dos títulos de gráfico
       do Qlik ("TRENDS", "WORLD ACTIVITY", "SALES SCENARIOS" etc.). */
    [data-testid="stMarkdownContainer"] h5 {
        font-weight: 700; color: #1D2939; font-size: 0.85rem;
        text-transform: uppercase; letter-spacing: 0.04em;
        border-bottom: 2px solid #EEF0F3; padding-bottom: 0.5rem;
        margin-bottom: 0.75rem;
    }

    /* Streamlit atual renderiza cada aba como [data-testid="stTab"] (não mais
       [data-baseweb="tab"]) - sem essa largura em "max-content", a caixa
       colorida da aba selecionada ficava mais estreita que o texto e cortava
       palavras como "Visão Geral" no meio. */
    .stTabs div:has(> [data-testid="stTab"]) {
        overflow: visible !important; gap: 4px; flex-wrap: wrap;
    }
    .stTabs [data-testid="stTab"] {
        background-color: transparent; border-radius: 0;
        padding: 0.5rem 0.9rem; border: none; border-bottom: 3px solid transparent;
        width: max-content !important; min-width: max-content !important;
        white-space: nowrap !important; overflow: visible !important;
        flex: 0 0 auto !important;
    }
    .stTabs [data-testid="stTab"] p {
        white-space: nowrap !important; font-weight: 600; color: #667085;
    }
    /* Aba selecionada no estilo Qlik: sem "bloco" preenchido, só um
       indicador colorido embaixo do texto (como a aba ativa nas telas do
       Qlik Sense, que também não usa preenchimento sólido). */
    .stTabs [data-testid="stTab"][aria-selected="true"] {
        background-color: transparent !important;
        border-bottom: 3px solid #7B48EA !important;
    }
    .stTabs [data-testid="stTab"][aria-selected="true"] p { color: #29184E !important; }

    /* Cards que envolvem cada gráfico - também mais "achatados" e com
       sombra leve em vez de borda roxa, igual aos painéis do Qlik. */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background-color: white; border-radius: 8px; border: 1px solid #E4E7EC;
        box-shadow: 0 1px 3px rgba(16, 24, 40, 0.05);
    }

    /* ------------------------------------------------------------------
       Esconde os elementos que o Streamlit Cloud injeta e que apontam para
       o código-fonte: menu de hambúrguer, botão "Deploy", a faixa colorida
       do topo, o rodapé "Made with Streamlit" e o badge/link "Fork this app"
       do GitHub.

       ATENÇÃO: isso é só cosmético. O repositório continua público no
       GitHub - o objetivo aqui é não deixar o convite óbvio na tela, não
       proteger o fonte. Nada sensível pode estar commitado (use st.secrets).

       Obs.: NÃO usamos "header { visibility: hidden }" de propósito, porque
       isso derrubaria junto a setinha que abre/fecha a sidebar no celular.
       Escondemos só a toolbar da direita.
       ------------------------------------------------------------------ */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    [data-testid="stToolbar"] { display: none !important; }
    [data-testid="stDecoration"] { display: none !important; }
    [data-testid="stStatusWidget"] { display: none !important; }
    [data-testid="stAppDeployButton"],
    .stAppDeployButton { display: none !important; }

    /* O badge "Fork this app" muda de classe a cada versão do Cloud, por
       isso o seletor genérico por prefixo em vez da classe exata. */
    [class*="viewerBadge"] { display: none !important; }
    .stApp a[href^="https://github.com"],
    .stApp a[href^="https://share.streamlit.io"],
    .stApp a[href^="https://streamlit.io"] { display: none !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


def grafico_tendencia_semanal(df_serie, coluna_categoria, categorias_ordenadas, titulo):
    """Uma linha por categoria (tag ou serviço), ao longo das semanas.

    Semanas sem nenhum chamado daquela categoria contam como 0 (em vez de
    ficarem sem ponto no gráfico) - assim a linha continua "inteira" ao
    longo de todo o período, e dá pra ver a tendência de cada categoria
    isoladamente, sem depender de comparar a altura de barras vizinhas."""
    df_serie = df_serie.copy()
    df_serie["semana_rotulo"] = df_serie["semana"].apply(rotulo_semana)
    rotulos_ordenados = (
        df_serie[["semana", "semana_rotulo"]]
        .drop_duplicates()
        .sort_values("semana")["semana_rotulo"]
        .tolist()
    )

    pivot = (
        df_serie.pivot_table(index=coluna_categoria, columns="semana_rotulo", values="qtd", aggfunc="sum")
        .reindex(index=categorias_ordenadas, columns=rotulos_ordenados)
        .fillna(0)
    )

    fig = go.Figure()
    for i, categoria in enumerate(categorias_ordenadas):
        cor = COLOR_SEQUENCE[i % len(COLOR_SEQUENCE)]
        fig.add_trace(go.Scatter(
            x=rotulos_ordenados, y=pivot.loc[categoria].tolist(),
            name=str(categoria), mode="lines+markers",
            line=dict(color=cor, width=2), marker=dict(size=5),
            hovertemplate="%{y} tickets<extra>" + str(categoria) + "</extra>",
        ))

    fig.update_layout(xaxis_title="", yaxis_title="Tickets", legend_title="", hovermode="x unified")
    fig.update_xaxes(showgrid=False, type="category", categoryorder="array", categoryarray=rotulos_ordenados)
    fig.update_yaxes(showgrid=True, gridcolor="#EEF2F6", zeroline=False, rangemode="tozero")
    fig = grafico(fig, titulo)
    # Com até 8 categorias, a legenda horizontal em cima (padrão do
    # grafico()) quebrava em várias linhas e cobria o topo do gráfico - uma
    # legenda vertical do lado direito não tem esse problema.
    fig.update_layout(
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
        margin=dict(r=180),
        height=420,
    )
    return fig


def grafico(fig, titulo=None):
    """Aplica um layout padrão (fundo, margens, fonte) a um gráfico Plotly."""
    fig.update_layout(
        margin=dict(l=10, r=10, t=30 if titulo else 10, b=10),
        title=titulo,
        font=dict(family="Segoe UI, Arial", size=13, color="#1D2939"),
        paper_bgcolor="white",
        plot_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def hex_para_rgba(hex_color: str, alpha: float) -> str:
    """Converte uma cor hexadecimal (ex.: '#7B48EA') numa string rgba com a
    transparência (alpha) informada - usado para preencher a área abaixo das
    linhas dos gráficos de área com uma versão mais clara da cor da linha."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def grafico_rosca(labels, values, titulo, hole=0.55):
    """Rosca (donut) 2D simples e limpa, sem efeitos extras."""
    n = len(labels)
    cores = [COLOR_SEQUENCE[i % len(COLOR_SEQUENCE)] for i in range(n)]

    fig = go.Figure()
    fig.add_trace(go.Pie(
        labels=labels, values=values, hole=hole, sort=False, direction="clockwise",
        marker=dict(colors=cores, line=dict(color="white", width=2)),
        textinfo="percent", textposition="inside", insidetextorientation="horizontal",
        hovertemplate="%{label}: %{value} tickets (%{percent})<extra></extra>",
    ))

    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=-0.1, xanchor="center", x=0.5),
    )
    fig = grafico(fig, titulo)
    fig.update_layout(height=420)
    return fig


def grafico_area_tempo_parado(df_just, titulo, cor):
    """Gráfico de área com um chamado (id) por ponto no eixo X, ordenado do
    que está parado há mais tempo para o que está há menos tempo, com o
    tempo parado (em horas corridas, que pode passar de 24h) no eixo Y."""
    df_just = df_just.sort_values("horas_parado", ascending=False)
    fig = px.area(df_just, x="id_str", y="horas_parado")
    fig.update_traces(line_color=cor, fillcolor=hex_para_rgba(cor, 0.25), mode="lines+markers")
    fig.update_layout(xaxis_title="", yaxis_title="Horas parado")
    fig.update_xaxes(categoryorder="array", categoryarray=df_just["id_str"].tolist(), tickangle=-35)
    fig.update_traces(hovertemplate="Chamado %{x}: %{y:.1f}h parado<extra></extra>")
    return grafico(fig, titulo)


PRAZO_CORES = {
    "No prazo": "#14B8A6", "Dentro do prazo": "#14B8A6",
    "Fora do prazo": "#EF4444", "Estourado": "#EF4444",
    "Sem SLA definido": "#CBD5E1",
}
GRUPO_CORES = {"Finalizado": COLOR_SEQUENCE[0], "Em atendimento": COLOR_SEQUENCE[3]}


def calcular_prazo(df_in: pd.DataFrame) -> pd.DataFrame:
    """Calcula, para tickets já atendidos (exclui status 'Novo'), se o SLA foi
    cumprido - usado tanto na aba Tempo & SLA quanto na Causa Raiz & Prazo,
    para os números baterem nas duas.

    - Finalizados (resolvidos/fechados): compara tempo até fechamento com o
      SLA de solução ("No prazo" / "Fora do prazo").
    - Em atendimento: compara o tempo já decorrido desde a abertura com o
      SLA de solução ("Dentro do prazo" / "Estourado").
    - Sem SLA cadastrado no ticket: "Sem SLA definido".
    """
    d = df_in[df_in["status_base"] != "New"].copy() if "status_base" in df_in.columns else df_in.copy()
    if d.empty:
        return d

    d["grupo_atendimento"] = np.where(
        d["status_base"].isin(["Resolved", "Closed"]), "Finalizado", "Em atendimento"
    )
    agora = pd.Timestamp(datetime.now(timezone.utc).replace(tzinfo=None))
    d["sla_horas"] = d["sla_tempo_solucao_min"] / 60 if "sla_tempo_solucao_min" in d.columns else np.nan

    def _prazo_status(row):
        if pd.isna(row.get("sla_horas")):
            return "Sem SLA definido"
        if row["grupo_atendimento"] == "Finalizado":
            if pd.isna(row.get("tempo_ate_fechamento_horas")):
                return "Sem SLA definido"
            return "No prazo" if row["tempo_ate_fechamento_horas"] <= row["sla_horas"] else "Fora do prazo"
        if pd.isna(row.get("data_abertura")):
            return "Sem SLA definido"
        decorrido = (agora - row["data_abertura"]).total_seconds() / 3600
        return "Estourado" if decorrido > row["sla_horas"] else "Dentro do prazo"

    d["prazo_status"] = d.apply(_prazo_status, axis=1)
    return d


def resumo_prazo(d: pd.DataFrame):
    """A partir do resultado de calcular_prazo(), separa finalizados/em
    atendimento e calcula os percentuais de cumprimento de SLA."""
    finalizados = d[d["grupo_atendimento"] == "Finalizado"]
    em_atend = d[d["grupo_atendimento"] == "Em atendimento"]

    fin_com_sla = finalizados[finalizados["prazo_status"].isin(["No prazo", "Fora do prazo"])]
    pct_no_prazo = (fin_com_sla["prazo_status"] == "No prazo").mean() * 100 if not fin_com_sla.empty else None

    atend_com_sla = em_atend[em_atend["prazo_status"].isin(["Dentro do prazo", "Estourado"])]
    pct_estourado = (atend_com_sla["prazo_status"] == "Estourado").mean() * 100 if not atend_com_sla.empty else None

    return finalizados, em_atend, fin_com_sla, atend_com_sla, pct_no_prazo, pct_estourado


# --------------------------------------------------------------------------
# BARRA LATERAL: ATUALIZAR DADOS
# --------------------------------------------------------------------------

def atualizar_dados(full: bool, days: int = None):
    if days is not None:
        label = f"Buscando tickets criados nos últimos {days} dias..."
    elif full:
        label = (
            "Fazendo carga completa (todo o histórico)... isso pode levar bastante tempo "
            "se houver muitos tickets (o Movidesk limita 10 requisições por minuto)."
        )
    else:
        label = "Buscando só os tickets novos/alterados desde a última atualização..."

    with st.spinner(label):
        df_novo = movidesk.run_extraction(full=full, days=days)
        movidesk.export_excel_backup()

    st.cache_data.clear()
    if df_novo.empty:
        st.info("Nenhum ticket novo ou alterado. A base já estava em dia.")
    else:
        st.success(f"Dados atualizados! {len(df_novo)} tickets enviados ao Supabase.")


with st.sidebar:
    st.header("📥 Dados")
    dias_input = st.number_input(
        "Buscar tickets dos últimos quantos dias?",
        min_value=1, max_value=90, value=30, step=1,
        help="O botão abaixo sempre busca tickets criados dentro desse período.",
    )

    if st.button("🔄 Atualizar dados do Movidesk", width="stretch"):
        atualizar_dados(full=False, days=int(dias_input))
        st.rerun()

    with st.expander("Opções avançadas"):
        st.caption(
            "Carga completa: busca todo o histórico de tickets, não só o "
            "período acima. Pode demorar bastante se houver muitos tickets."
        )
        if st.button("Forçar carga completa (histórico inteiro)", width="stretch"):
            atualizar_dados(full=True)
            st.rerun()


# --------------------------------------------------------------------------
# CARREGAMENTO DOS DADOS (do Supabase)
# --------------------------------------------------------------------------

st.markdown(
    """
    <div class="app-header">
        <h1>📊 Dashboard de Suporte Técnico</h1>
        <p>Indicadores e tickets do Movidesk, atualizados via Supabase</p>
    </div>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=300)
def load_data() -> pd.DataFrame:
    df = db.read_tickets()
    for col in DATE_COLS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    if "origem" in df.columns:
        df["origem_nome"] = df["origem"].map(ORIGIN_LABELS).fillna(df["origem"].astype("string"))
    return df


df = load_data()

if df.empty:
    st.warning(
        "Nenhum dado encontrado no Supabase ainda. Clique em **'Atualizar dados do "
        "Movidesk'** na barra lateral para fazer a primeira extração."
    )
    st.stop()


# --------------------------------------------------------------------------
# FILTROS
# --------------------------------------------------------------------------

with st.sidebar:
    st.header("🔎 Filtros")

    datas_validas = df["data_abertura"].dropna()
    if not datas_validas.empty:
        min_date, max_date = datas_validas.min().date(), datas_validas.max().date()
        # Padrão sempre nos últimos 30 dias (a partir do ticket mais recente),
        # mesmo que existam tickets mais antigos na base - o usuário ainda pode
        # ampliar manualmente o período usando os limites min_value/max_value.
        inicio_padrao = max(min_date, max_date - pd.Timedelta(days=29))
        date_range = st.date_input(
            "Período de abertura",
            value=(inicio_padrao, max_date),
            min_value=min_date,
            max_value=max_date,
        )
    else:
        date_range = None

    def multiselect_coluna(label, coluna):
        """Retorna (selecionados, opções completas). Tickets com valor em
        branco nessa coluna não aparecem na lista de opções (não dá pra
        selecionar "vazio" num filtro) - por isso o filtro só é aplicado de
        fato quando o usuário tira alguma opção da seleção padrão; enquanto
        estiver tudo selecionado, os tickets em branco continuam aparecendo
        normalmente.

        Usa st.pills (botões que acendem/apagam) em vez de st.multiselect:
        o multiselect padrão do Streamlit tinha um bug visual de renderização
        (a "pilula" da primeira tag selecionada aparecia cortada) que não foi
        possível corrigir de forma confiável só com CSS."""
        opcoes = sorted(df[coluna].dropna().unique().tolist()) if coluna in df.columns else []
        if not opcoes:
            return [], []
        selecionados = st.pills(label, opcoes, selection_mode="multi", default=opcoes)
        return (selecionados or []), opcoes

    status_sel, status_opcoes = multiselect_coluna("Status", "status")
    categoria_sel, categoria_opcoes = multiselect_coluna("Categoria", "categoria")
    urgencia_sel, urgencia_opcoes = multiselect_coluna("Urgência", "urgencia")
    equipe_sel, equipe_opcoes = multiselect_coluna("Equipe responsável", "equipe_responsavel")

mask = pd.Series(True, index=df.index)

if isinstance(date_range, tuple) and len(date_range) == 2 and df["data_abertura"].notna().any():
    inicio, fim = date_range
    mask &= df["data_abertura"].dt.date.between(inicio, fim)

for coluna, selecionados, opcoes in [
    ("status", status_sel, status_opcoes),
    ("categoria", categoria_sel, categoria_opcoes),
    ("urgencia", urgencia_sel, urgencia_opcoes),
    ("equipe_responsavel", equipe_sel, equipe_opcoes),
]:
    # Só filtra de verdade se o usuário tirou alguma opção do padrão
    # (todas selecionadas). Assim, tickets com essa coluna em branco não
    # somem "de graça" - só se o usuário realmente restringir a seleção.
    if coluna in df.columns and set(selecionados) != set(opcoes):
        mask &= df[coluna].isin(selecionados)

dff = df[mask]

st.caption(f"Exibindo {len(dff)} de {len(df)} tickets — fonte: Supabase")

if dff.empty:
    st.info("Nenhum ticket encontrado para os filtros selecionados.")
    st.stop()


# --------------------------------------------------------------------------
# KPIs (sempre visíveis, acima das abas)
# --------------------------------------------------------------------------

abertos_base = {"New", "InAttendance", "Stopped"}

total = len(dff)
abertos = int(dff["status_base"].isin(abertos_base).sum()) if "status_base" in dff else None
resolvidos = int((dff["status_base"] == "Resolved").sum()) if "status_base" in dff else None
fechados = int((dff["status_base"] == "Closed").sum()) if "status_base" in dff else None
tempo_medio = dff["tempo_ate_resolucao_horas"].mean() if "tempo_ate_resolucao_horas" in dff else None
fcr = (
    dff["resolvido_primeiro_atendimento"].mean() * 100
    if "resolvido_primeiro_atendimento" in dff and dff["resolvido_primeiro_atendimento"].notna().any()
    else None
)

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Total de tickets", total)
col2.metric("Em aberto", abertos if abertos is not None else "—")
col3.metric("Resolvidos", resolvidos if resolvidos is not None else "—")
col4.metric("Fechados", fechados if fechados is not None else "—")
col5.metric("Tempo médio p/ resolução", f"{tempo_medio:.1f} h" if pd.notna(tempo_medio) else "—")
col6.metric("Resolvido no 1º atendimento", f"{fcr:.0f}%" if fcr is not None and pd.notna(fcr) else "—")

st.write("")

# Cálculo de cumprimento de SLA, compartilhado pelas abas Tempo & SLA e
# Causa Raiz & Prazo (evita duplicar a lógica e garante que os números
# batam nas duas abas). Considera só tickets já atendidos (exclui 'Novo').
dcr = calcular_prazo(dff)


# --------------------------------------------------------------------------
# ABAS
# --------------------------------------------------------------------------

aba_geral, aba_equipe, aba_tempo, aba_causa, aba_detalhado = st.tabs(
    [
        "📌 Visão Geral", "👥 Equipe", "⏱️ Tempo & SLA",
        "🎯 Causa Raiz & Prazo", "📋 Detalhado",
    ]
)

# --- Visão Geral -----------------------------------------------------------
with aba_geral:
    c1, c2 = st.columns(2)
    with c1:
        if "status" in dff.columns:
            contagem = dff.groupby("status").size().reset_index(name="qtd").sort_values("qtd", ascending=False)
            fig = px.bar(contagem, x="status", y="qtd", text="qtd", color="status")
            fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Tickets")
            st.plotly_chart(grafico(fig, "Tickets por status"), width="stretch")
    with c2:
        if "urgencia" in dff.columns:
            contagem = dff.groupby("urgencia").size().reset_index(name="qtd").sort_values("qtd", ascending=False)
            fig = px.bar(contagem, x="urgencia", y="qtd", text="qtd", color="urgencia")
            fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Tickets")
            st.plotly_chart(grafico(fig, "Tickets por urgência"), width="stretch")

    c3, c4 = st.columns(2)
    with c3:
        if "servico_nivel1" in dff.columns and dff["servico_nivel1"].notna().any():
            contagem = (
                dff.groupby("servico_nivel1").size().reset_index(name="qtd")
                .sort_values("qtd", ascending=False).head(15)
            )
            fig = px.area(contagem, x="servico_nivel1", y="qtd")
            fig.update_traces(
                line_color=COLOR_SEQUENCE[2], fillcolor=hex_para_rgba(COLOR_SEQUENCE[2], 0.25),
                mode="lines+markers",
            )
            fig.update_layout(xaxis_title="", yaxis_title="Tickets")
            fig.update_xaxes(categoryorder="array", categoryarray=contagem["servico_nivel1"].tolist(), tickangle=-35)
            st.plotly_chart(grafico(fig, "Tickets por serviço (nível 1)"), width="stretch")
        else:
            st.info("Sem dados de serviço (nível 1) para os filtros atuais.")
    with c4:
        if "servico_nivel2" in dff.columns and dff["servico_nivel2"].notna().any():
            contagem = (
                dff.groupby("servico_nivel2").size().reset_index(name="qtd")
                .sort_values("qtd", ascending=False).head(15)
            )
            fig = px.area(contagem, x="servico_nivel2", y="qtd")
            fig.update_traces(
                line_color=COLOR_SEQUENCE[8], fillcolor=hex_para_rgba(COLOR_SEQUENCE[8], 0.25),
                mode="lines+markers",
            )
            fig.update_layout(xaxis_title="", yaxis_title="Tickets")
            fig.update_xaxes(categoryorder="array", categoryarray=contagem["servico_nivel2"].tolist(), tickangle=-35)
            st.plotly_chart(grafico(fig, "Tickets por serviço (nível 2)"), width="stretch")
        else:
            st.info("Sem dados de serviço (nível 2) para os filtros atuais.")

    c5, c6 = st.columns(2)
    with c5:
        if "categoria" in dff.columns:
            # Limitado a 10 fatias (em vez das 15 do gráfico de barras
            # anterior) - rosca com muitas fatias finas fica ilegível.
            contagem = (
                dff.groupby("categoria").size().reset_index(name="qtd")
                .sort_values("qtd", ascending=False).head(10)
            )
            fig = grafico_rosca(
                contagem["categoria"].tolist(), contagem["qtd"].tolist(), "Tickets por Categoria",
            )
            st.plotly_chart(fig, width="stretch")
    with c6:
        if "origem_nome" in dff.columns:
            contagem = dff.groupby("origem_nome").size().reset_index(name="qtd").sort_values("qtd", ascending=False)
            fig = grafico_rosca(
                contagem["origem_nome"].tolist(), contagem["qtd"].tolist(), "Tickets por canal de abertura",
            )
            st.plotly_chart(fig, width="stretch")

    # Evolução semanal: compara volume de tickets ABERTOS (demanda) com
    # FINALIZADOS (resolvidos ou fechados) por semana. Isso mostra se o
    # backlog está crescendo (abertos > finalizados) ou diminuindo.
    tem_abertura = "data_abertura" in dff.columns and dff["data_abertura"].notna().any()
    tem_fechamento = "data_fechamento" in dff.columns
    tem_resolucao = "data_resolucao" in dff.columns

    if tem_abertura:
        serie_abertos = dff.dropna(subset=["data_abertura"]).copy()
        serie_abertos["semana"] = serie_abertos["data_abertura"].dt.to_period("W").apply(lambda p: p.start_time)
        abertos_semana = serie_abertos.groupby("semana").size().reset_index(name="qtd")

        data_final = None
        if tem_fechamento:
            data_final = dff["data_fechamento"]
        if tem_resolucao:
            data_final = dff["data_resolucao"] if data_final is None else data_final.fillna(dff["data_resolucao"])

        finalizados_semana = None
        if data_final is not None and data_final.notna().any():
            serie_fin = dff.copy()
            serie_fin["data_finalizacao"] = data_final
            serie_fin = serie_fin.dropna(subset=["data_finalizacao"])
            serie_fin["semana"] = serie_fin["data_finalizacao"].dt.to_period("W").apply(lambda p: p.start_time)
            finalizados_semana = serie_fin.groupby("semana").size().reset_index(name="qtd")

        # Mesmo tratamento de rótulo "D a D mês" usado no gráfico de tendência
        # semanal (tags/serviço), para manter a leitura consistente entre os
        # gráficos e garantir a ordem cronológica correta no eixo.
        todas_semanas = pd.concat([
            abertos_semana["semana"],
            finalizados_semana["semana"] if finalizados_semana is not None else pd.Series(dtype="datetime64[ns]"),
        ]).drop_duplicates().sort_values()
        rotulos_ordenados = [rotulo_semana(s) for s in todas_semanas]

        abertos_semana["semana_rotulo"] = abertos_semana["semana"].apply(rotulo_semana)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=abertos_semana["semana_rotulo"], y=abertos_semana["qtd"], name="Abertos",
            mode="lines+markers", line=dict(color="#EF4444", width=2.5),
            fill="tozeroy", fillcolor="rgba(239, 68, 68, 0.15)",
            hovertemplate="%{y} tickets<extra>Abertos</extra>",
        ))

        if finalizados_semana is not None:
            finalizados_semana["semana_rotulo"] = finalizados_semana["semana"].apply(rotulo_semana)
            fig.add_trace(go.Scatter(
                x=finalizados_semana["semana_rotulo"], y=finalizados_semana["qtd"], name="Finalizados",
                mode="lines+markers", line=dict(color="#14B8A6", width=2.5),
                fill="tozeroy", fillcolor="rgba(20, 184, 166, 0.15)",
                hovertemplate="%{y} tickets<extra>Finalizados</extra>",
            ))

        fig.update_layout(xaxis_title="", yaxis_title="Tickets", legend_title="", hovermode="x unified")
        fig.update_xaxes(showgrid=False, type="category", categoryorder="array", categoryarray=rotulos_ordenados)
        fig.update_yaxes(showgrid=True, gridcolor="#EEF2F6", zeroline=False)
        st.plotly_chart(grafico(fig, "Evolução semanal: abertos x finalizados"), width="stretch")

# --- Equipe ------------------------------------------------------------------
with aba_equipe:
    c1, c2 = st.columns(2)
    with c1:
        if "equipe_responsavel" in dff.columns:
            contagem = dff.groupby("equipe_responsavel").size().reset_index(name="qtd").sort_values("qtd", ascending=False)
            fig = px.bar(contagem, x="equipe_responsavel", y="qtd", text="qtd", color="equipe_responsavel")
            fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Tickets")
            st.plotly_chart(grafico(fig, "Tickets por equipe responsável"), width="stretch")
    with c2:
        if "responsavel" in dff.columns and dff["responsavel"].notna().any():
            contagem = (
                dff.groupby("responsavel").size().reset_index(name="qtd")
                .sort_values("qtd", ascending=False).head(15)
            )
            fig = px.bar(contagem, x="qtd", y="responsavel", orientation="h", text="qtd")
            fig.update_layout(yaxis={"categoryorder": "total ascending"}, xaxis_title="Tickets", yaxis_title="")
            fig.update_traces(marker_color=COLOR_SEQUENCE[5])
            st.plotly_chart(grafico(fig, "Top 15 responsáveis"), width="stretch")
        else:
            st.info("Sem dados de responsável individual para os filtros atuais.")

# --- Tempo & SLA ---------------------------------------------------------------
def gauge_sla(valor, titulo):
    """Gauge 0-100% para indicadores de cumprimento de SLA."""
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=round(valor, 1),
        number={"suffix": "%", "font": {"size": 34, "color": "#1D2939"}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": "#94A3B8", "tickfont": {"size": 10}},
            "bar": {"color": "#29184E", "thickness": 0.3},
            "bgcolor": "white",
            "borderwidth": 0,
            "steps": [
                {"range": [0, 70], "color": "#FEE2E2"},
                {"range": [70, 90], "color": "#FEF3C7"},
                {"range": [90, 100], "color": "#D1FAE5"},
            ],
        },
        title={"text": titulo, "font": {"size": 14, "color": "#475467"}},
    ))
    fig.update_layout(height=230, margin=dict(l=25, r=25, t=50, b=10), paper_bgcolor="white")
    return fig


with aba_tempo:
    st.caption(
        "Cumprimento de SLA considera tickets já atendidos (finalizados ou "
        "em atendimento) que têm um SLA de solução cadastrado no Movidesk."
    )

    if dcr.empty:
        st.info("Nenhum ticket em atendimento/finalizado para os filtros atuais.")
    else:
        finalizados, em_atend, fin_com_sla, atend_com_sla, pct_no_prazo, pct_estourado = resumo_prazo(dcr)
        pct_atend_no_prazo = 100 - pct_estourado if pct_estourado is not None else None

        tempo_medio_resolucao = dff["tempo_ate_resolucao_horas"].mean() if "tempo_ate_resolucao_horas" in dff else None
        tempo_medio_fechamento = dff["tempo_ate_fechamento_horas"].mean() if "tempo_ate_fechamento_horas" in dff else None

        st.markdown("##### Cumprimento de SLA")

        g1, g2, m1, m2 = st.columns([1.2, 1.2, 1, 1])
        with g1:
            if pct_no_prazo is not None:
                st.plotly_chart(gauge_sla(pct_no_prazo, "Finalizados no prazo"), width="stretch")
            else:
                st.info("Sem SLA cadastrado nos tickets finalizados.")
        with g2:
            if pct_atend_no_prazo is not None:
                st.plotly_chart(gauge_sla(pct_atend_no_prazo, "Em atendimento dentro do prazo"), width="stretch")
            else:
                st.info("Sem SLA cadastrado nos tickets em atendimento.")
        with m1:
            st.metric("Tempo médio até resolução", f"{tempo_medio_resolucao:.1f} h" if pd.notna(tempo_medio_resolucao) else "—")
            st.metric("Finalizados (no período)", len(finalizados))
        with m2:
            st.metric("Tempo médio até fechamento", f"{tempo_medio_fechamento:.1f} h" if pd.notna(tempo_medio_fechamento) else "—")
            st.metric("Em atendimento (no período)", len(em_atend))

        st.write("")
        st.markdown("##### Cumprimento de SLA por causa raiz (tag)")

        if "tags" in dcr.columns:
            com_sla = dcr[dcr["prazo_status"] != "Sem SLA definido"].copy()
            if not com_sla.empty:
                com_sla["status_sla"] = com_sla["prazo_status"].map({
                    "No prazo": "No prazo", "Dentro do prazo": "No prazo",
                    "Fora do prazo": "Fora do prazo", "Estourado": "Fora do prazo",
                })
                tags_sla = com_sla[["tags", "status_sla"]].copy()
                tags_sla["tag"] = tags_sla["tags"].fillna("").str.split(",")
                tags_sla = tags_sla.explode("tag")
                tags_sla["tag"] = tags_sla["tag"].str.strip().replace("", "Sem tag")

                top_tags_sla = list(
                    tags_sla.groupby("tag").size().sort_values(ascending=False).head(10).index
                )
                tags_sla = tags_sla[tags_sla["tag"].isin(top_tags_sla)]

                contagem = tags_sla.groupby(["tag", "status_sla"]).size().reset_index(name="qtd")
                totais = contagem.groupby("tag")["qtd"].transform("sum")
                contagem["pct"] = (contagem["qtd"] / totais * 100).round(0)
                contagem["rotulo"] = contagem["pct"].astype(int).astype(str) + "%"
                ordem_tags_sla = list(
                    contagem.groupby("tag")["qtd"].sum().sort_values(ascending=False).index
                )
                fig = px.bar(
                    contagem, x="pct", y="tag", color="status_sla", orientation="h",
                    text="rotulo",
                    color_discrete_map=PRAZO_CORES,
                    category_orders={
                        "status_sla": ["No prazo", "Fora do prazo"],
                        "tag": ordem_tags_sla[::-1],
                    },
                )
                fig.update_traces(textposition="inside", insidetextanchor="middle")
                fig.update_layout(
                    barmode="stack", xaxis_title="% dos tickets", yaxis_title="", legend_title="",
                    xaxis=dict(range=[0, 100], ticksuffix="%"),
                )
                st.plotly_chart(grafico(fig, "Cumprimento de SLA por causa raiz (top 10 tags)"), width="stretch")
            else:
                st.info("Nenhum ticket com SLA cadastrado para calcular por tag.")
        else:
            st.info("Coluna 'tags' não disponível.")

        st.write("")
        st.markdown("##### Tempo de atendimento por categoria")

        if {"categoria", "tempo_vida_horas_uteis_min"}.issubset(dff.columns):
            # Tempo ÚTIL de atendimento = tempo de vida em horário comercial
            # (lifeTimeWorkingTime do Movidesk) menos o tempo em que o chamado
            # ficou parado/aguardando (stoppedTime), convertido para horas.
            # Diferente do tempo corrido (data_resolucao - data_abertura), este
            # desconta noites, fins de semana e pausas - é o "tempo de mão na
            # massa" de atendimento.
            base_util = dff[dff["categoria"].notna() & dff["tempo_vida_horas_uteis_min"].notna()].copy()
            parado = (
                base_util["tempo_parado_min"].fillna(0)
                if "tempo_parado_min" in base_util.columns else 0
            )
            base_util["tempo_util_horas"] = (
                (base_util["tempo_vida_horas_uteis_min"].fillna(0) - parado) / 60
            ).clip(lower=0)

            top_cats = base_util["categoria"].value_counts().head(10).index
            amostra = base_util[base_util["categoria"].isin(top_cats)]
            if not amostra.empty:
                resumo = (
                    amostra.groupby("categoria")["tempo_util_horas"]
                    .agg(media="mean", mediana="median")
                    .reset_index()
                    .sort_values("media", ascending=False)
                )
                ordem_cats = resumo["categoria"].tolist()

                plot_df = resumo.melt(
                    id_vars="categoria", value_vars=["media", "mediana"],
                    var_name="metrica", value_name="horas",
                )
                plot_df["metrica"] = plot_df["metrica"].map(
                    {"media": "Tempo médio", "mediana": "Tempo típico (mediana)"}
                )
                plot_df["rotulo"] = plot_df["horas"].round(1).astype(str) + "h"

                fig = px.bar(
                    plot_df, x="horas", y="categoria", color="metrica", orientation="h",
                    barmode="group", text="rotulo",
                    category_orders={
                        "categoria": ordem_cats[::-1],
                        "metrica": ["Tempo médio", "Tempo típico (mediana)"],
                    },
                    color_discrete_map={
                        "Tempo médio": COLOR_SEQUENCE[3],
                        "Tempo típico (mediana)": COLOR_SEQUENCE[0],
                    },
                )
                fig.update_traces(textposition="outside")
                fig.update_layout(xaxis_title="Horas úteis de atendimento", yaxis_title="", legend_title="")
                st.plotly_chart(
                    grafico(fig, "Tempo útil de atendimento por categoria (top 10 por volume)"),
                    width="stretch",
                )
                st.caption(
                    "Tempo útil = tempo de vida em horário comercial (horas úteis) menos o "
                    "tempo em que o chamado ficou parado/aguardando - desconta noites, fins de "
                    "semana e pausas. O tempo médio pode ser puxado para cima por poucos "
                    "chamados muito demorados; o tempo típico (mediana) mostra melhor a maioria "
                    "dos casos: metade dos chamados dessa categoria leva menos tempo que isso, e "
                    "a outra metade mais."
                )
            else:
                st.info("Sem dados suficientes de tempo útil de atendimento para os filtros atuais.")

        st.write("")
        st.markdown("##### Incidentes aguardando DEV")
        st.caption(
            "Considera chamados com categoria 'Incidente' e status 'Aguardando' **abertos "
            "dentro do período selecionado** na barra lateral. O tempo parado é calculado a "
            "partir da última atualização do chamado (coisa distinta da data de abertura) e "
            "pode passar de 24h - não é só o horário do dia, é o tempo corrido completo."
        )

        colunas_necessarias = {"categoria", "status", "justificativa", "ultima_atualizacao", "id"}
        if colunas_necessarias.issubset(dff.columns):
            base_dev = dff[
                (dff["categoria"] == "Incidente") & (dff["status"] == "Aguardando")
            ].dropna(subset=["ultima_atualizacao"]).copy()

            if base_dev.empty:
                st.info("Nenhum chamado de Incidente aguardando para os filtros atuais.")
            else:
                # ultima_atualizacao vem do Movidesk em UTC (3h à frente do
                # horário de Brasília). Convertendo os dois lados para
                # Brasília (agora - 3h e ultima_atualizacao - 3h), o
                # deslocamento de 3h se cancela na subtração - por isso dá
                # pra usar "agora" direto em UTC (mesmo padrão usado em
                # calcular_prazo()) que o resultado em horas é o mesmo.
                agora_utc = pd.Timestamp(datetime.now(timezone.utc).replace(tzinfo=None))
                base_dev["horas_parado"] = (
                    (agora_utc - base_dev["ultima_atualizacao"]).dt.total_seconds() / 3600
                )
                base_dev["id_str"] = base_dev["id"].astype(str)

                cd1, cd2 = st.columns(2)
                with cd1:
                    analise = base_dev[base_dev["justificativa"] == "Análise DEV"]
                    if not analise.empty:
                        st.metric(
                            "Tempo médio em 'Análise DEV'",
                            f"{analise['horas_parado'].mean():.1f} h",
                        )
                        st.plotly_chart(
                            grafico_area_tempo_parado(
                                analise, "Parados em 'Análise DEV'", COLOR_SEQUENCE[4],
                            ),
                            width="stretch",
                        )
                    else:
                        st.info("Nenhum chamado em 'Análise DEV' no momento.")
                with cd2:
                    correcao = base_dev[base_dev["justificativa"] == "Correção DEV"]
                    if not correcao.empty:
                        st.metric(
                            "Tempo médio em 'Correção DEV'",
                            f"{correcao['horas_parado'].mean():.1f} h",
                        )
                        st.plotly_chart(
                            grafico_area_tempo_parado(
                                correcao, "Parados em 'Correção DEV'", COLOR_SEQUENCE[8],
                            ),
                            width="stretch",
                        )
                    else:
                        st.info("Nenhum chamado em 'Correção DEV' no momento.")

                # KPI consolidado, abaixo dos dois gráficos: tempo médio de
                # TODOS os chamados no time de Desenvolvimento (Análise DEV +
                # Correção DEV juntos), respeitando os mesmos filtros.
                # Feito com HTML próprio (em vez de st.metric) só para poder
                # centralizar o rótulo e o valor - o st.metric alinha à
                # esquerda e não dá pra centralizar apenas um card.
                dev = base_dev[base_dev["justificativa"].isin(["Análise DEV", "Correção DEV"])]
                if not dev.empty:
                    st.markdown(
                        f"""
                        <div style="background:white; border:1px solid #E4E7EC;
                             border-top:4px solid #7B48EA; border-radius:8px;
                             padding:1rem; margin-top:0.5rem; text-align:center;
                             box-shadow:0 1px 3px rgba(16,24,40,0.06);">
                            <div style="font-weight:700; color:#667085;
                                 text-transform:uppercase; font-size:0.72rem;
                                 letter-spacing:0.04em;">
                                Tempo médio total no Desenvolvimento (Análise + Correção DEV)
                            </div>
                            <div style="font-weight:700; color:#1D2939;
                                 font-size:2rem; margin-top:0.25rem;">
                                {dev['horas_parado'].mean():.1f} h
                            </div>
                            <div style="color:#98A2B3; font-size:0.72rem;">
                                Média de {len(dev)} chamado(s) em Análise DEV + Correção DEV
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
        else:
            st.info("Colunas necessárias (categoria/status/justificativa/ultima_atualizacao/id) não disponíveis.")

# --- Causa Raiz & Prazo -----------------------------------------------------
with aba_causa:
    st.caption(
        "Considera tickets que já tiveram atendimento iniciado (finalizados ou "
        "em atendimento) — exclui tickets ainda na fila, status 'Novo'."
    )

    if dcr.empty:
        st.info("Nenhum ticket em atendimento/finalizado para os filtros atuais.")
    else:
        finalizados, em_atend, fin_com_sla, atend_com_sla, pct_no_prazo, pct_estourado = resumo_prazo(dcr)

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Finalizados (no período)", len(finalizados))
        k2.metric("Em atendimento (no período)", len(em_atend))
        k3.metric("% finalizados no prazo", f"{pct_no_prazo:.0f}%" if pct_no_prazo is not None else "—")
        k4.metric("% em atendimento estourado", f"{pct_estourado:.0f}%" if pct_estourado is not None else "—")

        st.write("")

        c1, c2 = st.columns(2)
        with c1:
            if "tags" in dcr.columns:
                tags_df = dcr[["tags", "grupo_atendimento"]].copy()
                tags_df["tag"] = tags_df["tags"].fillna("").str.split(",")
                tags_df = tags_df.explode("tag")
                tags_df["tag"] = tags_df["tag"].str.strip().replace("", "Sem tag")

                top_tags = list(tags_df.groupby("tag").size().sort_values(ascending=False).head(15).index)
                contagem = (
                    tags_df[tags_df["tag"].isin(top_tags)]
                    .groupby(["tag", "grupo_atendimento"]).size().reset_index(name="qtd")
                )
                fig = px.bar(
                    contagem, x="qtd", y="tag", color="grupo_atendimento", orientation="h",
                    category_orders={"tag": top_tags[::-1]},
                    color_discrete_map=GRUPO_CORES,
                )
                fig.update_layout(xaxis_title="Tickets", yaxis_title="", legend_title="")
                st.plotly_chart(grafico(fig, "Maiores Incidentes por Causa Raiz(Tags)"), width="stretch")
            else:
                st.info("Coluna 'tags' não disponível.")

        with c2:
            if "servico_nivel1" in dcr.columns and dcr["servico_nivel1"].notna().any():
                coluna_servico = "servico_nivel1"
            elif "categoria" in dcr.columns:
                coluna_servico = "categoria"
            else:
                coluna_servico = None

            if coluna_servico:
                contagem_serv = (
                    dcr.dropna(subset=[coluna_servico])
                    .groupby([coluna_servico, "grupo_atendimento"]).size().reset_index(name="qtd")
                )
                top_serv = list(
                    contagem_serv.groupby(coluna_servico)["qtd"].sum()
                    .sort_values(ascending=False).head(15).index
                )
                contagem_serv = contagem_serv[contagem_serv[coluna_servico].isin(top_serv)]
                fig = px.bar(
                    contagem_serv, x="qtd", y=coluna_servico, color="grupo_atendimento", orientation="h",
                    category_orders={coluna_servico: top_serv[::-1]},
                    color_discrete_map=GRUPO_CORES,
                )
                fig.update_layout(xaxis_title="Tickets", yaxis_title="", legend_title="")
                st.plotly_chart(grafico(fig, "Maiores incidentes por serviço"), width="stretch")
            else:
                st.info("Sem coluna de serviço/categoria disponível.")

        if "data_abertura" in dcr.columns and dcr["data_abertura"].notna().any():
            st.markdown("##### Tendência semanal")

            dcr_tempo = dcr.dropna(subset=["data_abertura"]).copy()
            dcr_tempo["semana"] = dcr_tempo["data_abertura"].dt.to_period("W").apply(lambda p: p.start_time)

            # Tendência das principais causas raiz (tags) por semana
            if "tags" in dcr_tempo.columns:
                tags_tempo = dcr_tempo[["semana", "tags"]].copy()
                tags_tempo["tag"] = tags_tempo["tags"].fillna("").str.split(",")
                tags_tempo = tags_tempo.explode("tag")
                tags_tempo["tag"] = tags_tempo["tag"].str.strip().replace("", "Sem tag")

                top_tags_tempo = list(
                    tags_tempo.groupby("tag").size().sort_values(ascending=False).head(8).index
                )
                serie_tags = (
                    tags_tempo[tags_tempo["tag"].isin(top_tags_tempo)]
                    .groupby(["semana", "tag"]).size().reset_index(name="qtd")
                )
                fig = grafico_tendencia_semanal(
                    serie_tags, "tag", top_tags_tempo,
                    "Tendência semanal das principais causas raiz (tags)",
                )
                st.plotly_chart(fig, width="stretch")

            # Tendência de incidentes por serviço por semana
            if coluna_servico:
                serv_tempo = (
                    dcr_tempo.dropna(subset=[coluna_servico])
                    .groupby(["semana", coluna_servico]).size().reset_index(name="qtd")
                )
                top_serv_tempo = list(
                    serv_tempo.groupby(coluna_servico)["qtd"].sum()
                    .sort_values(ascending=False).head(8).index
                )
                serv_tempo = serv_tempo[serv_tempo[coluna_servico].isin(top_serv_tempo)]
                fig = grafico_tendencia_semanal(
                    serv_tempo, coluna_servico, top_serv_tempo,
                    "Tendência semanal de incidentes por serviço",
                )
                st.plotly_chart(fig, width="stretch")


# --- Detalhado -------------------------------------------------------------------
with aba_detalhado:
    st.dataframe(dff, width="stretch", height=450)
    csv = dff.to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇️ Baixar tickets filtrados (CSV)", csv, "tickets_filtrados.csv", "text/csv")
