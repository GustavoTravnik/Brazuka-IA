import os

# O QUE FAZ: Busca na web otimizada para LLMs — retorna resultados curados, resumos
#             de páginas e conteúdo relevante já processado para consumo pelo agente.
#             Diferente do Brave Search, o Tavily foca em qualidade e síntese do conteúdo.
# REQUER CHAVE: Sim.
#   TAVILY_API_KEY → obtenha gratuitamente (1.000 req/mês grátis) em:
#                    app.tavily.com → Sign up → API Keys

async def register(mcp_manager):
    api_key = os.getenv("TAVILY_API_KEY")

    if not api_key:
        print("[!] Tavily: TAVILY_API_KEY ausente no .env")
        return

    await mcp_manager.connect_server(
        name="tavily",
        command="npx",
        args=["-y", "tavily-mcp@latest"],
        env={
            "TAVILY_API_KEY": api_key
        }
    )
