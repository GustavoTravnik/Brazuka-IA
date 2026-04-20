import os

# O QUE FAZ: Integração com MongoDB / AWS DocumentDB — executa queries, lista collections,
#             inspeciona schemas e analisa dados diretamente via URI de conexão.
# REQUER CHAVE: Não exige chave de API, mas requer URI de conexão ao banco.
#   MONGODB_URI  → URI completa (ex: mongodb://user:pass@host:27017/dbname)
#   ou
#   MONGODB_HOST → host do servidor (ex: localhost ou endpoint do DocumentDB)
#   MONGODB_PORT → porta (padrão: 27017)
#   Defina no .env do projeto.

async def register(mcp_manager):
    mongodb_uri = os.getenv("MONGODB_URI")
    mongodb_host = os.getenv("MONGODB_HOST")
    mongodb_port = os.getenv("MONGODB_PORT", "27017")

    if not mongodb_uri and not mongodb_host:
        print("[!] DocumentDB: Variáveis MONGODB_URI ou MONGODB_HOST não encontradas.")
        return

    env = {}
    if mongodb_uri:
        env["MONGODB_URI"] = mongodb_uri
    else:
        env["MONGODB_HOST"] = mongodb_host
        env["MONGODB_PORT"] = mongodb_port

    await mcp_manager.connect_server(
        name="documentdb",
        command="uvx",
        args=["documentdb-mcp[all]==0.1.45"],
        env=env,
    )
