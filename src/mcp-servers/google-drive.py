import os

# O QUE FAZ: Integração com Google Drive — pesquisa, lê e exporta arquivos do Drive,
#             incluindo Google Docs, Sheets e Slides convertidos para texto/markdown.
#             Permite ao agente acessar documentos e planilhas corporativas diretamente.
# REQUER CHAVE: Sim (OAuth 2.0 do Google).
#   Passo a passo:
#   1. Acesse: console.cloud.google.com → New Project
#   2. Ative a API: APIs & Services → Enable APIs → Google Drive API
#   3. Crie credenciais: APIs & Services → Credentials → OAuth 2.0 Client ID → Desktop App
#   4. Baixe o credentials.json e salve em: ~/.coia/gdrive-credentials.json
#   5. Na primeira execução, o browser abrirá para autorizar o acesso.

async def register(mcp_manager):
    credentials_path = os.getenv(
        "GDRIVE_CREDENTIALS_PATH",
        "/home/ogt100749/.coia/gdrive-credentials.json"
    )

    if not os.path.exists(credentials_path):
        print(f"[!] Google Drive: arquivo de credenciais não encontrado em '{credentials_path}'")
        return

    await mcp_manager.connect_server(
        name="google-drive",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-gdrive"],
        env={
            "GDRIVE_CREDENTIALS_PATH": credentials_path,
            "PATH": os.getenv("PATH", "")
        }
    )
