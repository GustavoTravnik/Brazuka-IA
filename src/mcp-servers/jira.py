import os

# O QUE FAZ: Integração com Jira — lista issues, cria e atualiza tickets, adiciona comentários,
#             gerencia sprints e transições de status via API Atlassian.
# REQUER CHAVE: Sim.
#   JIRA_USER_EMAIL  → email da conta Atlassian (ex: joao@empresa.com)
#   JIRA_API_TOKEN   → token gerado em:
#                      id.atlassian.net → Security → API tokens → Create API token

async def register(mcp_manager):
    token = os.getenv("JIRA_API_TOKEN")
    email = os.getenv("JIRA_USER_EMAIL")
    site = os.getenv("JIRA_SITE")

    if not token or not email:
        print("[!] Jira: Variáveis JIRA_API_TOKEN ou JIRA_USER_EMAIL não encontradas.")
        return

    await mcp_manager.connect_server(
        name="jira",
        command="npx",
        args=["-y", "@aashari/mcp-server-atlassian-jira@latest"],
        env={
            "ATLASSIAN_SITE_NAME": site,
            "ATLASSIAN_USER_EMAIL": email,
            "ATLASSIAN_API_TOKEN": token
        }
    )
