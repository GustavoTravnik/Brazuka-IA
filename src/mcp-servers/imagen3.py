import os

# O QUE FAZ: Geração de imagens de alta qualidade via Google Imagen 3 — especializado em
#             fotorrealismo, arte e controle de estilo fotográfico. Suporta prompts detalhados
#             com parâmetros de câmera, iluminação e composição artística.
# REQUER CHAVE: Sim.
#   GOOGLE_AI_API_KEY → obtenha gratuitamente em: aistudio.google.com → Get API Key
#                       Plano gratuito disponível com limites generosos.

async def register(mcp_manager):
    api_key = os.getenv("GOOGLE_AI_API_KEY")

    if not api_key:
        print("[!] Imagen 3: GOOGLE_AI_API_KEY ausente no .env")
        return

    await mcp_manager.connect_server(
        name="imagen3",
        command="npx",
        args=["-y", "@hamflx/imagen3-mcp@latest"],
        env={
            "GOOGLE_AI_API_KEY": api_key
        }
    )
