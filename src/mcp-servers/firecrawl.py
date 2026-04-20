import os

# O QUE FAZ: Scraping avançado de páginas web — extrai conteúdo limpo em markdown,
#             realiza crawling de sites inteiros, mapeia URLs e executa buscas indexadas.
#             Superior ao fetch simples para sites com JavaScript ou conteúdo dinâmico.
# REQUER CHAVE: Sim.
#   FIRECRAWL_API_KEY → obtenha em: firecrawl.dev → Sign up → API Keys
#                       Plano gratuito disponível com limite mensal de requisições.

async def register(mcp_manager):
    api_key = os.getenv("FIRECRAWL_API_KEY")

    if not api_key:
        print("[!] Firecrawl: FIRECRAWL_API_KEY ausente no .env")
        return

    await mcp_manager.connect_server(
        name="firecrawl",
        command="npx",
        args=["-y", "firecrawl-mcp"],
        env={
            "FIRECRAWL_API_KEY": api_key
        }
    )
