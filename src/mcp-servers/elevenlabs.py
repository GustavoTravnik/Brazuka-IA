import os

# O QUE FAZ: Síntese de voz (TTS) via ElevenLabs — converte texto em áudio com vozes
#             realistas, clonagem de voz, controle de emoção e prosódia. Gera arquivos
#             de áudio MP3/WAV prontos para uso em vídeos, podcasts e aplicações.
# REQUER CHAVE: Sim.
#   ELEVENLABS_API_KEY → obtenha gratuitamente (10.000 caracteres/mês grátis) em:
#                        elevenlabs.io → Sign up → Profile → API Key

async def register(mcp_manager):
    api_key = os.getenv("ELEVENLABS_API_KEY")

    if not api_key:
        print("[!] ElevenLabs: ELEVENLABS_API_KEY ausente no .env")
        return

    await mcp_manager.connect_server(
        name="elevenlabs",
        command="uvx",
        args=["elevenlabs-mcp"],
        env={
            "ELEVENLABS_API_KEY": api_key
        }
    )
