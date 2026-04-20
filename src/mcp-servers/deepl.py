import os

# O QUE FAZ: Tradução profissional de textos via DeepL — suporta 30+ idiomas com qualidade
#             superior ao Google Translate para textos técnicos e formais. Traduz documentos
#             inteiros mantendo formatação e glossários customizados.
# REQUER CHAVE: Sim.
#   DEEPL_API_KEY → obtenha gratuitamente (500.000 caracteres/mês grátis) em:
#                   deepl.com/pro-api → Sign up for free → Copy Authentication Key

async def register(mcp_manager):
    api_key = os.getenv("DEEPL_API_KEY")

    if not api_key:
        print("[!] DeepL: DEEPL_API_KEY ausente no .env")
        return

    await mcp_manager.connect_server(
        name="deepl",
        command="npx",
        args=["-y", "@kimtth/mcp-deepl-translate@latest"],
        env={
            "DEEPL_API_KEY": api_key
        }
    )
