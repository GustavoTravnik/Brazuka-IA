import os

# O QUE FAZ: Integração com Bitbucket — navega repositórios, lê código, cria e revisa
#             pull requests, gerencia branches e pipelines via API Atlassian.
# REQUER CHAVE: Sim.
#   BITBUCKET_USERNAME   → seu usuário Bitbucket (ex: joao.silva)
#   BITBUCKET_APP_PASSWORD → App Password gerado em:
#                            bitbucket.org → Settings → App passwords → Create
#                            Permissões necessárias: Repositories (Read/Write), Pull requests (Read/Write)

async def register(mcp_manager):
    app_password = os.getenv("BITBUCKET_APP_PASSWORD")
    username = os.getenv("BITBUCKET_USERNAME")

    if not app_password or not username:
        print("[!] Bitbucket: BITBUCKET_APP_PASSWORD ou BITBUCKET_USERNAME ausente no .env")
        return

    await mcp_manager.connect_server(
        name="bitbucket",
        command="npx",
        args=["-y", "@aashari/mcp-server-atlassian-bitbucket@latest"],
        env={
            "ATLASSIAN_BITBUCKET_USERNAME": username,
            "ATLASSIAN_BITBUCKET_APP_PASSWORD": app_password
        }
    )
