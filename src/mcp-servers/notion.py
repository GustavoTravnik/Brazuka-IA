import os

# O QUE FAZ: Integração completa com Notion — lê, cria e edita páginas, databases e blocos.
#             Permite ao agente consultar wikis, atualizar documentações, criar tarefas
#             e interagir com qualquer workspace do Notion de forma programática.
# REQUER CHAVE: Sim.
#   NOTION_API_KEY → obtenha em: notion.so/my-integrations → New integration → Submit
#                    Depois compartilhe as páginas desejadas com a integração criada.

async def register(mcp_manager):
    api_key = os.getenv("NOTION_API_KEY")

    if not api_key:
        print("[!] Notion: NOTION_API_KEY ausente no .env")
        return

    await mcp_manager.connect_server(
        name="notion",
        command="npx",
        args=["-y", "@notionhq/notion-mcp-server@latest"],
        env={
            "OPENAPI_MCP_HEADERS": f'{{"Authorization": "Bearer {api_key}", "Notion-Version": "2022-06-28"}}'
        }
    )
