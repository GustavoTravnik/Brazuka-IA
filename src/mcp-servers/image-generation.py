import os

# O QUE FAZ: Geração e edição de imagens via OpenAI — suporta DALL-E 3 e GPT-Image-1.
#             Cria imagens a partir de prompts de texto, edita imagens existentes e
#             gera variações. Salva os resultados localmente ou retorna como base64.
# REQUER CHAVE: Sim.
#   OPENAI_API_KEY → obtenha em: platform.openai.com → API Keys → Create new secret key
#                    Requer conta com créditos. Geração de imagem custa ~$0.04–$0.08/imagem.

async def register(mcp_manager):
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        print("[!] Image Generation: OPENAI_API_KEY ausente no .env")
        return

    await mcp_manager.connect_server(
        name="image-generation",
        command="npx",
        args=["-y", "@sureScaleAI/openai-gpt-image-mcp@latest"],
        env={
            "OPENAI_API_KEY": api_key
        }
    )
