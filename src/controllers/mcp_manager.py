import os
import asyncio
import importlib.util
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class MCPManager:
    def __init__(self):
        self.sessions = {}
        self.exit_stack = AsyncExitStack()

    MCP_CONNECT_TIMEOUT = 30  # segundos — tempo máximo para conectar um servidor MCP

    async def connect_server(self, name, command, args, env):
        server_params = StdioServerParameters(
            command=command,
            args=args,
            env={**os.environ, **env}
        )

        try:
            stdio_transport = await asyncio.wait_for(
                self.exit_stack.enter_async_context(stdio_client(server_params)),
                timeout=self.MCP_CONNECT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            print(f"[!] MCP '{name}': timeout após {self.MCP_CONNECT_TIMEOUT}s — servidor ignorado.")
            return
        except Exception as e:
            print(f"[!] MCP '{name}': falha ao conectar — {e} — servidor ignorado.")
            return

        read, write = stdio_transport
        session = await self.exit_stack.enter_async_context(ClientSession(read, write))

        try:
            await asyncio.wait_for(session.initialize(), timeout=self.MCP_CONNECT_TIMEOUT)
        except asyncio.TimeoutError:
            print(f"[!] MCP '{name}': timeout na inicialização — servidor ignorado.")
            return
        except Exception as e:
            print(f"[!] MCP '{name}': falha na inicialização — {e} — servidor ignorado.")
            return

        self.sessions[name] = session
        print(f"\033[1;32m\n================== Servidor MCP '{name}' conectado. ==================")
        try:
            result = await asyncio.wait_for(session.list_tools(), timeout=10)
            print(f"[*] {len(result.tools)} ferramentas disponibilizadas pelo servidor '{name}':")
            tools_list = [f"    > {tool.name}" for tool in result.tools]
            print("".join(tools_list), "\n==========================\n\033[0m")
        except Exception as e:
            print(f"[!] Erro ao listar ferramentas de '{name}': {e}")

    async def initialize_standard_servers(self, allowed: list[str] | None = None):
        """
        Carrega e conecta servidores MCP.
        Se `allowed` for fornecido, somente os servidores cujo nome (slug do .py) estiver
        na lista serão inicializados. None = todos.
        """
        print("[*] Inicializando servidores MCP...")
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        servers_dir = os.path.join(base_dir, "mcp-servers")

        if not os.path.exists(servers_dir):
            return

        for filename in sorted(os.listdir(servers_dir)):
            if not filename.endswith(".py") or filename == "__init__.py":
                continue
            module_name = filename[:-3]
            if allowed is not None and module_name not in allowed:
                print(f"[~] MCP '{module_name}' ignorado (não selecionado pelo usuário).")
                continue
            file_path = os.path.join(servers_dir, filename)
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "register"):
                await module.register(self)

    async def get_all_tools(self):
        all_tools = []
        for server_name, session in self.sessions.items():
            result = await session.list_tools()
            for tool in result.tools:
                # Sempre prefixa com o nome do servidor para garantir unicidade
                # e permitir que call_tool resolva o servidor pelo prefixo.
                display_name = f"{server_name}_{tool.name}"

                schema = tool.inputSchema
                if hasattr(schema, "model_dump"):
                    schema = schema.model_dump()
                elif hasattr(schema, "dict"):
                    schema = schema.dict()

                all_tools.append({
                    "name": display_name,
                    "description": tool.description,
                    "input_schema": schema,
                })
        return all_tools

    async def call_tool(self, full_name: str, arguments: dict) -> str:
        parts = full_name.split("_", 1)
        if len(parts) < 2:
            return f"Erro: nome de ferramenta inválido — esperado '<servidor>_<tool>', recebido '{full_name}'."

        server_name, tool_name = parts[0], parts[1]
        session = self.sessions.get(server_name)
        if not session:
            return f"Erro: servidor MCP '{server_name}' não encontrado."

        try:
            result = await session.call_tool(tool_name, arguments)
            return "\n".join(str(b.text) for b in result.content if hasattr(b, "text"))
        except Exception as e:
            return f"Erro ao executar '{full_name}': {e}"

    async def cleanup(self):
        try:
            await self.exit_stack.aclose()
        except Exception as e:
            # Mitiga falha conhecida de encerramento do anyio/mcp em alguns ambientes.
            # Sem isso, a sprint conclui mas o processo termina em erro durante o shutdown.
            if "Attempted to exit cancel scope in a different task" in self._collect_exception_messages(e):
                print("[!] Aviso: erro conhecido no shutdown MCP foi ignorado para finalizar a execução com segurança.")
                return
            raise

    def _collect_exception_messages(self, exc):
        messages = []
        stack = [exc]
        seen = set()

        while stack:
            current = stack.pop()
            ident = id(current)
            if ident in seen:
                continue
            seen.add(ident)

            messages.append(str(current))

            nested = getattr(current, "exceptions", None)
            if nested:
                stack.extend([n for n in nested if n is not None])

            cause = getattr(current, "__cause__", None)
            context = getattr(current, "__context__", None)
            if cause is not None:
                stack.append(cause)
            if context is not None:
                stack.append(context)

        return "\n".join(messages)
