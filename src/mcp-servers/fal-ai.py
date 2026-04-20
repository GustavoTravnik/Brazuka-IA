import os

# O QUE FAZ: Geração de imagens, vídeos e áudio via Fal.ai — acesso a modelos como
#             Flux, Stable Diffusion, LoRA customizadas e pipelines de vídeo.
#             Alternativa ao DALL-E com mais modelos open-source e controle criativo.
# REQUER CHAVE: Sim.
#   FAL_KEY → obtenha em: fal.ai → Sign up → Dashboard → API Keys → Add Key
#              Plano pay-per-use. Geração de imagem a partir de ~$0.003/imagem (Flux Schnell).

async def register(mcp_manager):
    api_key = os.getenv("FAL_KEY")

    if not api_key:
        print("[!] Fal.ai: FAL_KEY ausente no .env")
        return

    await mcp_manager.connect_server(
        name="fal-ai",
        command="uvx",
        args=["fal-mcp"],
        env={
            "FAL_KEY": api_key
        }
    )
