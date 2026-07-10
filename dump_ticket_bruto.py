"""
Inspeciona o JSON bruto de alguns tickets reais do Movidesk
=============================================================

Por quê este script existe
----------------------------
A coluna "cliente" do dashboard depende de como a SUA conta do Movidesk usa
os campos "clients" (lista de solicitantes) e "createdBy" (quem abriu o
ticket) - isso varia de empresa pra empresa. Sem ver dados reais não dá pra
ter certeza se o campo "organization" (empresa vinculada ao solicitante)
está preenchido, ou se o nome certo pra usar é outro.

Este script busca alguns tickets (sem limitar os campos com $select, pra
trazer TUDO que a API tiver) e salva o JSON bruto em um arquivo, além de
mostrar na tela um resumo de "clients" e "createdBy" de cada um.

COMO USAR
---------
    python dump_ticket_bruto.py

(usa a mesma variável de ambiente MOVIDESK_TOKEN que o extrai_movidesk.py -
configure do mesmo jeito, via .streamlit/secrets.toml ou variável de ambiente)

Depois, abra o arquivo tickets_brutos.json gerado e veja, para cada ticket:
- Se "clients" tem algum item, e se esse item tem "organization" preenchido.
- Se "createdBy" tem "organization" preenchido.
- Ou se nenhum dos dois tem nada útil (aí precisamos de outra fonte pro
  "cliente", tipo um campo customizado do ticket).

Me manda o que aparecer (pode apagar nomes/e-mails reais se quiser, só
preciso ver a ESTRUTURA dos campos) que eu ajusto a extração.
"""

import json
import os

import requests

MOVIDESK_TOKEN = os.environ.get("MOVIDESK_TOKEN")
BASE_URL = "https://api.movidesk.com/public/v1"
QUANTIDADE = 5

if MOVIDESK_TOKEN in (None, "", "COLE_SEU_TOKEN_AQUI"):
    print("ERRO: configure a variável de ambiente MOVIDESK_TOKEN antes de rodar "
          "(mesma configuração usada pelo extrai_movidesk.py).")
    raise SystemExit(1)

print(f"Buscando os últimos {QUANTIDADE} tickets (todos os campos, sem $select)...")
resp = requests.get(
    f"{BASE_URL}/tickets",
    params={
        "token": MOVIDESK_TOKEN,
        "$top": QUANTIDADE,
        "$orderby": "id desc",
    },
    timeout=60,
)
resp.raise_for_status()
tickets = resp.json()

with open("tickets_brutos.json", "w", encoding="utf-8") as f:
    json.dump(tickets, f, ensure_ascii=False, indent=2, default=str)

print(f"\nSalvo em tickets_brutos.json ({len(tickets)} tickets).\n")
print("=" * 70)

for t in tickets:
    print(f"\nTicket #{t.get('id')} - {t.get('subject')}")

    clients = t.get("clients")
    print(f"  clients: {clients!r}")
    if isinstance(clients, list) and clients:
        primeiro = clients[0]
        print(f"    -> primeiro cliente: businessName={primeiro.get('businessName')!r} "
              f"personName={primeiro.get('personName')!r} "
              f"organization={primeiro.get('organization')!r}")

    created_by = t.get("createdBy")
    print(f"  createdBy: {created_by!r}")
    if isinstance(created_by, dict):
        print(f"    -> businessName={created_by.get('businessName')!r} "
              f"personName={created_by.get('personName')!r} "
              f"organization={created_by.get('organization')!r}")

print("\n" + "=" * 70)
print("Confira o arquivo tickets_brutos.json pra ver a estrutura completa.")
