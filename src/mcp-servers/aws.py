import os

# O QUE FAZ: Integração com AWS CDK — documentação, constructs, regras CDK Nag e padrões
#             de soluções AWS. Útil para gerar e revisar infraestrutura como código.
# REQUER CHAVE: Não exige chave de API, mas requer perfil AWS configurado localmente
#               (~/.aws/credentials). Configure com: aws configure --profile <nome>

async def register(mcp_manager):
    aws_profile = os.getenv("AWS_PROFILE", "gustavo.travnik")
    aws_region = os.getenv("AWS_REGION", "us-east-1")

    print(f"[*] AWS: Conectando via perfil '{aws_profile}' (Modo Direct API)...")

    await mcp_manager.connect_server(
        name="aws",
        command="uvx",
        args=[
            "awslabs.cdk-mcp-server@latest"
        ],
        env={
            "AWS_PROFILE": aws_profile,
            "AWS_REGION": aws_region,
        }
    )
