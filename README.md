# Dashboard de Suporte Técnico — Movidesk

Dashboard em Streamlit para acompanhar os chamados de suporte técnico do
Movidesk: KPIs, evolução semanal, causa raiz, cumprimento de SLA e mais.
Os dados ficam armazenados no Supabase (Postgres) e são atualizados sob
demanda direto da API do Movidesk.

## Estrutura do projeto

- `dashboard.py` — o app Streamlit (dashboard com abas, gráficos e filtros).
- `extrai_movidesk.py` — extrai os tickets da API do Movidesk e grava no Supabase.
- `db.py` — conexão com o Supabase (leitura/escrita), compartilhada pelos dois arquivos acima.
- `testar_conexao.py` — script de diagnóstico da conexão com o Supabase.
- `iniciar_dashboard.bat` — atalho para Windows: instala dependências e abre o dashboard.
- `requirements.txt` — dependências Python do projeto.

## Configuração (segredos)

Este projeto precisa de duas credenciais, configuradas como variáveis de
ambiente (nunca direto no código):

- `MOVIDESK_TOKEN` — token de API do Movidesk (Movidesk > Configurações > Conta > Parâmetros > aba "Ambiente").
- `SUPABASE_DB_URL` — connection string do Postgres do Supabase (Session pooler).

### Rodando localmente

1. Copie `.streamlit/secrets.toml.example` para `.streamlit/secrets.toml`.
2. Preencha os dois valores reais nesse arquivo.
3. Instale as dependências: `pip install -r requirements.txt`
4. Rode: `streamlit run dashboard.py` (ou dê duplo clique em `iniciar_dashboard.bat` no Windows).

O `.streamlit/secrets.toml` já está no `.gitignore` — ele nunca é enviado ao Git.

### Publicando no Streamlit Community Cloud

1. Suba este repositório para o GitHub (veja instruções de deploy fornecidas separadamente).
2. Em [share.streamlit.io](https://share.streamlit.io), clique em "New app" e selecione o repositório, branch e o arquivo principal `dashboard.py`.
3. Antes (ou depois) do deploy, vá em **Settings > Secrets** do app e cole o mesmo conteúdo do seu `.streamlit/secrets.toml` (com os valores reais).
4. Pronto — o app builda e fica disponível numa URL pública do tipo `https://SEU-APP.streamlit.app`.

## Atualizando os dados

Pela própria interface do dashboard (barra lateral): escolha quantos dias
de histórico buscar e clique em "Atualizar dados do Movidesk". A primeira
carga pode ser feita por período (mais rápida) ou completa (histórico
inteiro, em "Opções avançadas").
