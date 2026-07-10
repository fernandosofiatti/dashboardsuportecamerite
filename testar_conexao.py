"""
Teste rápido de conexão com o Supabase
=========================================

Roda em poucos segundos e mostra exatamente onde está o problema, caso
exista: rede, autenticação, tabela, permissão de escrita, etc.

COMO USAR
---------
Abra um terminal (cmd/PowerShell) NA PASTA deste arquivo e rode:

    python testar_conexao.py

Deixe a janela aberta e copie a saída inteira caso algo dê errado - ela
já vem com mensagens explicando cada etapa.

O script grava um ticket de teste no Supabase para validar escrita/leitura
e depois REMOVE esse registro automaticamente (senão ele atrapalharia a
atualização incremental do extrai_movidesk.py).
"""

import sys
import traceback

print("=" * 60)
print("TESTE DE CONEXÃO COM O SUPABASE")
print("=" * 60)

# --------------------------------------------------------------------------
# 1. As bibliotecas necessárias estão instaladas?
# --------------------------------------------------------------------------
print("\n[1/5] Verificando bibliotecas instaladas...")
try:
    import psycopg2
    import sqlalchemy
    import pandas as pd
    print(f"  OK - psycopg2 {psycopg2.__version__}")
    print(f"  OK - sqlalchemy {sqlalchemy.__version__}")
    print(f"  OK - pandas {pd.__version__}")
except ImportError as exc:
    print(f"  FALHOU: {exc}")
    print("\n  Solução: rode 'pip install -r requirements.txt' nesta pasta e tente de novo.")
    sys.exit(1)

# --------------------------------------------------------------------------
# 2. Consegue importar o db.py?
# --------------------------------------------------------------------------
print("\n[2/5] Carregando configuração (db.py)...")
try:
    import db
    print(f"  OK - Tabela configurada: {db.TABLE_NAME}")
    # Mostra a connection string escondendo a senha
    url = db.SUPABASE_DB_URL
    if "@" in url:
        head, tail = url.split("@", 1)
        if ":" in head:
            user_part = head.rsplit(":", 1)[0]
            url_oculta = f"{user_part}:****@{tail}"
        else:
            url_oculta = f"{head}@{tail}"
    else:
        url_oculta = url
    print(f"  Connection string: {url_oculta}")
except Exception as exc:
    print(f"  FALHOU: {exc}")
    sys.exit(1)

# --------------------------------------------------------------------------
# 3. Consegue abrir uma conexão de verdade com o Postgres do Supabase?
# --------------------------------------------------------------------------
print("\n[3/5] Tentando conectar no banco...")
try:
    conn = db.get_connection()
    print("  OK - conexão aberta com sucesso!")
except Exception:
    print("  FALHOU ao conectar. Erro completo abaixo:\n")
    traceback.print_exc()
    print(
        "\n  Causas comuns: senha errada, connection string errada, firewall/"
        "antivírus bloqueando a porta 5432, ou rede sem acesso ao Supabase."
    )
    sys.exit(1)

# --------------------------------------------------------------------------
# 4. Consegue criar a tabela (ou ela já existe com a estrutura certa)?
# --------------------------------------------------------------------------
print("\n[4/5] Verificando/criando a tabela (CREATE TABLE IF NOT EXISTS)...")
try:
    db.ensure_table()
    print(f"  OK - tabela '{db.TABLE_NAME}' existe e está acessível.")
except Exception:
    print("  FALHOU ao criar/verificar a tabela. Erro completo abaixo:\n")
    traceback.print_exc()
    sys.exit(1)

# --------------------------------------------------------------------------
# 5. Consegue GRAVAR e LER um registro de teste?
# --------------------------------------------------------------------------
print("\n[5/5] Testando escrita e leitura de um ticket de teste...")
try:
    import pandas as pd
    from datetime import datetime, timezone

    df_teste = pd.DataFrame([{
        "id": "TESTE-CONEXAO-999999",
        "protocolo": "TESTE",
        "assunto": "Ticket de teste (pode apagar)",
        "categoria": "Teste",
        "urgencia": None,
        "status": "Teste",
        "status_base": "New",
        "justificativa": None,
        "origem": 1,
        "servico_nivel1": None,
        "servico_nivel2": None,
        "servico_nivel3": None,
        "tags": "",
        "responsavel": None,
        "equipe_responsavel": None,
        "criado_por": None,
        "cliente": None,
        "data_abertura": datetime.now(timezone.utc).replace(tzinfo=None),
        "data_resolucao": None,
        "data_fechamento": None,
        "data_reabertura": None,
        "ultima_acao": None,
        "ultima_atualizacao": datetime.now(timezone.utc).replace(tzinfo=None),
        "qtd_acoes": 0,
        "tempo_vida_horas_uteis_min": None,
        "tempo_parado_min": None,
        "resolvido_primeiro_atendimento": False,
        "sla_contrato": None,
        "sla_tempo_solucao_min": None,
        "sla_tempo_resposta_min": None,
        "tempo_ate_resolucao_horas": None,
        "tempo_ate_fechamento_horas": None,
    }])

    enviados = db.upsert_tickets(df_teste)
    print(f"  OK - upsert_tickets() gravou {enviados} registro(s).")

    contagem = db.count_tickets()
    print(f"  OK - a tabela agora tem {contagem} registro(s) no total.")

    df_leitura = db.read_tickets()
    achou = "TESTE-CONEXAO-999999" in df_leitura["id"].astype(str).values
    if achou:
        print("  OK - consegui ler de volta o ticket de teste.")
    else:
        print("  ATENÇÃO - gravei mas não consegui ler de volta o ticket de teste.")
        print("  Isso pode indicar um problema de permissão de leitura (RLS?).")

except Exception:
    print("  FALHOU ao gravar/ler o ticket de teste. Erro completo abaixo:\n")
    traceback.print_exc()
    sys.exit(1)

# --------------------------------------------------------------------------
# Limpeza: remove o registro de teste (ele NÃO pode ficar na tabela, senão
# atrapalha a atualização incremental do extrai_movidesk.py - o script usa
# o "ultima_atualizacao" mais recente da tabela pra saber desde quando
# buscar tickets novos, e um registro de teste com data de agora faria ele
# achar que já está tudo sincronizado).
# --------------------------------------------------------------------------
try:
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f'DELETE FROM {db.TABLE_NAME} WHERE id = %s', ("TESTE-CONEXAO-999999",))
        conn.commit()
    print("  OK - registro de teste removido da tabela (limpeza automática).")
except Exception as exc:
    print(f"  ATENÇÃO - não consegui remover o registro de teste automaticamente: {exc}")
    print("  Apague manualmente antes de rodar a extração de verdade:")
    print(f"  DELETE FROM {db.TABLE_NAME} WHERE id = 'TESTE-CONEXAO-999999';")

print("\n" + "=" * 60)
print("TUDO OK! A conexão com o Supabase está funcionando de ponta a ponta.")
print("=" * 60)
print(
    "\nSe mesmo assim os dados do Movidesk não aparecem depois de rodar "
    "o extrai_movidesk.py, o problema está na parte de buscar dados da "
    "API do Movidesk, não na conexão com o Supabase."
)
