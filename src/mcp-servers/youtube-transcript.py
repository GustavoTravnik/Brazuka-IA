import os

# O QUE FAZ: Extrai a transcrição completa de qualquer vídeo do YouTube — retorna o texto
#             legendado em português, inglês ou qualquer idioma disponível no vídeo.
#             Útil para resumir vídeos, extrair informações e analisar conteúdo sem assistir.
# REQUER CHAVE: Não. Funciona sem nenhuma configuração, desde que o vídeo tenha legendas.

async def register(mcp_manager):
    await mcp_manager.connect_server(
        name="youtube-transcript",
        command="npx",
        args=["-y", "@kimtaeyoon83/mcp-server-youtube-transcript@latest"],
        env={}
    )
