import os

# O QUE FAZ: Busca na web em tempo real via Brave Search — retorna resultados relevantes,
#             snippets e URLs sem rastreamento. Suporta busca web, imagens, notícias e vídeos.
#             Essencial para o agente obter informações atualizadas fora do contexto de treino.
# REQUER CHAVE: Sim.
#   BRAVE_API_KEY → obtenha gratuitamente (até 2.000 req/mês) em:
#                   brave.com/search/api → Sign up → Create API Key

async def register(mcp_manager):
    api_key = os.getenv("BRAVE_API_KEY")

    if not api_key:
        print("[!] Brave Search: BRAVE_API_KEY ausente no .env")
        return

    await mcp_manager.connect_server(
        name="brave-search",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-brave-search"],
        env={
            "BRAVE_API_KEY": api_key
        }
    )
