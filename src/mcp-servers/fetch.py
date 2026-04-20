import os

# O QUE FAZ: Busca e converte o conteúdo de qualquer URL em markdown limpo para consumo
#             pelo agente. Suporta páginas HTML, documentações e artigos. Ideal para
#             pesquisa rápida na web sem precisar de browser automation.
# REQUER CHAVE: Não. Funciona sem nenhuma configuração.

async def register(mcp_manager):
    await mcp_manager.connect_server(
        name="fetch",
        command="uvx",
        args=["mcp-server-fetch"],
        env={}
    )
