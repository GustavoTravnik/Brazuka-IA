import os

# O QUE FAZ: Sistema de memória persistente baseado em grafo de conhecimento — o agente
#             pode criar, atualizar e consultar entidades e relações entre sessões.
#             Permite que o COIA "lembre" de contextos, projetos e decisões anteriores
#             sem depender apenas do contexto da conversa atual.
# REQUER CHAVE: Não. A memória é armazenada localmente em arquivo JSON.

async def register(mcp_manager):
    memory_path = os.getenv("MEMORY_FILE_PATH", "/home/ogt100749/.coia/memory.json")

    await mcp_manager.connect_server(
        name="memory",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-memory"],
        env={
            "MEMORY_FILE_PATH": memory_path
        }
    )
