import os

# O QUE FAZ: Integração com Gmail — lê, busca, envia e organiza emails diretamente
#             pelo agente. Permite criar rascunhos, responder threads, aplicar labels
#             e gerenciar a caixa de entrada de forma automatizada.
# REQUER CHAVE: Sim (OAuth 2.0 do Google — mesmo projeto do Google Drive se já configurado).
#   Passo a passo:
#   1. Acesse: console.cloud.google.com → seu projeto (ou crie novo)
#   2. Ative a API: APIs & Services → Enable APIs → Gmail API
#   3. Crie credenciais: APIs & Services → Credentials → OAuth 2.0 Client ID → Desktop App
#   4. Baixe o credentials.json e salve em: ~/.coia/gmail-credentials.json
#   5. Na primeira execução, o browser abrirá para autorizar o acesso à conta Gmail.

async def register(mcp_manager):
    credentials_path = os.getenv(
        "GMAIL_CREDENTIALS_PATH",
        "/home/ogt100749/.coia/gmail-credentials.json"
    )

    if not os.path.exists(credentials_path):
        print(f"[!] Gmail: arquivo de credenciais não encontrado em '{credentials_path}'")
        return

    await mcp_manager.connect_server(
        name="gmail",
        command="npx",
        args=["-y", "@gongrzhe/server-gmail-autoauth-mcp@latest"],
        env={
            "CREDENTIALS_PATH": credentials_path,
            "PATH": os.getenv("PATH", "")
        }
    )
