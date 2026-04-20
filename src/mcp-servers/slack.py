import os

# O QUE FAZ: Integração com Slack — lê mensagens de canais, envia mensagens, lista canais
#             e usuários, e interage com workspaces via API oficial do Slack.
# REQUER CHAVE: Sim.
#   SLACK_BOT_TOKEN → token do bot gerado em: api.slack.com → Your Apps → OAuth & Permissions
#                     Criar um app, adicionar scopes (channels:read, chat:write, etc.) e instalar no workspace.
#   SLACK_TEAM_ID   → ID do workspace (visível na URL: app.slack.com/client/TXXXXXXXX)

async def register(mcp_manager):
    slack_token = os.getenv("SLACK_BOT_TOKEN")
    slack_team = os.getenv("SLACK_TEAM_ID")

    if not slack_token:
        print("[!] Slack: SLACK_BOT_TOKEN ausente no .env")
        return

    await mcp_manager.connect_server(
        name="slack",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-slack"],
        env={
            "SLACK_BOT_TOKEN": slack_token,
            "SLACK_TEAM_ID": slack_team,
            "PATH": os.getenv("PATH", "")
        }
    )
