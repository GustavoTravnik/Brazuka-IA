import os
import re
import sys
import uuid
import asyncio
import traceback
import argparse
from dotenv import load_dotenv

import google.generativeai as genai
from google.generativeai import types

from controllers.agent_orchestrator import Orquestrador
from controllers.command_manager import CommandManager
from controllers.skill_manager import SkillManager
from controllers.mcp_manager import MCPManager
from controllers.native_tools import NativeToolsManager
from controllers.thinking_stream import stream_with_thinking
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.key_binding import KeyBindings

load_dotenv()

MODEL_NAME  = os.getenv("MODEL_GEMINI", "gemini-1.5-flash")
API_KEY     = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    print("❌ Erro: GEMINI_API_KEY não encontrada no arquivo .env")
    sys.exit(1)

genai.configure(api_key=API_KEY, transport='rest')

class DummyUsage:
    def __init__(self, input_tokens, output_tokens, cache_read_input_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens

class DummyBlock:
    def __init__(self, type, text=None, id=None, name=None, input=None):
        self.type = type
        self.text = text
        self.id = id
        self.name = name
        self.input = input

class DummyResponse:
    def __init__(self, content, usage, stop_reason):
        self.content = content
        self.usage = usage
        self.stop_reason = stop_reason

class DummyStream:
    def __init__(self, model, max_tokens, system, messages, tools):
        self.model_name = model
        self.max_tokens = max_tokens
        self.system = system
        self.messages = messages
        self.tools = tools

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def _generate_response(self):
        if hasattr(self, "_cached_resp"):
            return self._cached_resp
        
        full_model_name = self.model_name if self.model_name.startswith("models/") else f"models/{self.model_name}"

        google_tools = []
        if self.tools:
            function_declarations = []
            for t in self.tools:
                function_declarations.append({
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {})
                })
            if function_declarations:
                google_tools = [{"function_declarations": function_declarations}]

        system_text = ""
        if isinstance(self.system, list):
            for s in self.system:
                if s.get("type") == "text":
                    system_text += s.get("text", "") + "\n"
        elif isinstance(self.system, str):
            system_text = self.system

        model = genai.GenerativeModel(
            model_name=full_model_name,
            system_instruction=system_text if system_text else None,
            tools=google_tools if google_tools else None
        )

        google_contents = []
        for m in self.messages:
            role = "model" if m["role"] == "assistant" else "user"
            parts = []
            content = m["content"]
            
            if isinstance(content, str):
                parts.append({"text": content})
            elif isinstance(content, list):
                for block in content:
                    if block.get("type") == "text":
                        parts.append({"text": block.get("text", "")})
                    elif block.get("type") == "tool_use":
                        parts.append({"function_call": {"name": block.get("name"), "args": block.get("input", {})}})
                    elif block.get("type") == "tool_result":
                        tool_name = "unknown"
                        for prev_m in reversed(self.messages):
                            if prev_m["role"] == "assistant" and isinstance(prev_m["content"], list):
                                for b in prev_m["content"]:
                                    if b.get("id") == block.get("tool_use_id"):
                                        tool_name = b.get("name")
                                        break
                        parts.append({
                            "function_response": {
                                "name": tool_name,
                                "response": {"result": block.get("content")}
                            }
                        })
            if parts:
                google_contents.append({"role": role, "parts": parts})

        response = await asyncio.to_thread(
            model.generate_content,
            contents=google_contents,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=self.max_tokens,
                temperature=0.0
            )
        )

        content_blocks = []
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.text:
                    content_blocks.append(DummyBlock(type="text", text=part.text))
                elif part.function_call:
                    call_id = f"call_{uuid.uuid4().hex[:8]}"
                    args = {k: v for k, v in part.function_call.args.items()}
                    content_blocks.append(DummyBlock(
                        type="tool_use",
                        id=call_id,
                        name=part.function_call.name,
                        input=args
                    ))

        usage_md = response.usage_metadata
        usage = DummyUsage(
            input_tokens=usage_md.prompt_token_count,
            output_tokens=usage_md.candidates_token_count,
            cache_read_input_tokens=getattr(usage_md, "cached_content_token_count", 0)
        )

        stop_reason = "end_turn"
        finish_reason = response.candidates[0].finish_reason if response.candidates else None
        if finish_reason == 2:
            stop_reason = "max_tokens"

        self._cached_resp = DummyResponse(content=content_blocks, usage=usage, stop_reason=stop_reason)
        return self._cached_resp

    async def get_final_message(self):
        return await self._generate_response()

    async def __aiter__(self):
        resp = await self._generate_response()
        
        class TextDelta:
            def __init__(self, text):
                self.text = text
                
        class RawContentBlockDeltaEvent:
            def __init__(self, text):
                self.delta = TextDelta(text)
                
        for b in resp.content:
            if b.type == "text":
                yield RawContentBlockDeltaEvent(b.text)

class DummyMessages:
    def stream(self, model, max_tokens, system, messages, tools):
        return DummyStream(model, max_tokens, system, messages, tools)

class AsyncAnthropicMock:
    def __init__(self):
        self.messages = DummyMessages()

def _build_client() -> AsyncAnthropicMock:
    return AsyncAnthropicMock()

def max_tokens_for(model: str) -> int:
    return 8192


USD_TO_BRL   = 5.60 # Ajustado para 2026
PRICE_IN     = (0.075 / 1_000_000) * USD_TO_BRL # Preços Gemini 1.5 Flash      
PRICE_OUT    = (0.30  / 1_000_000) * USD_TO_BRL
PRICE_CACHE  = (0.01  / 1_000_000) * USD_TO_BRL

CYAN, BLUE, RED, GREEN, BLUE_BOLD, RESET, BOLD = (
    "\033[96m", "\033[94m", "\033[1;31m", "\033[1;32m",
    "\033[1;34m", "\033[0m", "\033[1m"
)

LOGO_LINES = [
    f"{CYAN}{BOLD}    ==========================================",
    f"           ______ _____ ______    _    ",
    f"          / ____|/ __ \\|_   _|   / \\   ",
    f"         | |    | |  | | | |    / _ \\  ",
    f"         | |____| |__| |_| |_  / ___ \\ ",
    f"          \\____/ \\____/|_____|/_/   \\_\\",
    f"                                       ",
    f"              AI CLI ASSISTANT v2.5",
    f"              ",
    f"    =========================================={RESET}",
]
def set_terminal_title(model: str, t_in: int = 0, t_out: int = 0, t_cache: int = 0) -> None:
    if t_in or t_out or t_cache:
        sys.stdout.write(f"\033]0;COIA — {model} | {t_in}↑ {t_out}↓ cache:{t_cache}\007")
    else:
        sys.stdout.write(f"\033]0;COIA — {model}\007")
    sys.stdout.flush()

def clear_console() -> None:
    os.system("cls" if os.name == "nt" else "clear")

_LOGO_WIDTH = 44  # largura interna do banner (entre as bordas)

def _centered_in_logo(text: str) -> str:
    """Centraliza `text` dentro da largura do banner, com padding de espaços."""
    padded = text.center(_LOGO_WIDTH)
    return f"    {padded}"

def print_logo(model: str = "") -> None:
    print()
    for line in LOGO_LINES:
        print(line)
    if model:
        label = f"[ {model} ]"
        print(f"{BLUE_BOLD}{_centered_in_logo(label)}{RESET}")
    print(f"{CYAN}{BOLD}    {'=' * _LOGO_WIDTH}{RESET}")
    print()
    sys.stdout.flush()

def print_usage(c_in: int, c_out: int, c_cache: int,
                t_in: int, t_out: int, t_cache: int,
                call_cost: float, total_cost: float, total_discount: float,
                show: bool = True) -> None:
    if not show:
        return
    print(
        f"{RED}"
        f"\r [Tokens: {c_in}↑ {c_out}↓ cache:{c_cache} | "
        f"Total: {t_in}↑ {t_out}↓ cache:{t_cache} | "
        f"R${call_cost:.4f} / R${total_cost:.2f} (-R${total_discount:.2f})]"
        f"{RESET}"
    )

def is_project_root() -> bool:
    return os.path.exists("agent.md")

def extract_agent_skills(agent_content: str) -> list[str]:
    """
    Procura por '@Useful-Skills=[skill1,skill2,...]' nas últimas linhas do agent.md.
    Retorna lista de nomes de skills ou lista vazia se não encontrado.
    """
    match = re.search(r"@Useful-Skills\s*=\s*\[?([^\]\n]+?)\]?\s*$", agent_content, re.MULTILINE)
    if not match:
        return []
    return [s.strip() for s in match.group(1).split(",") if s.strip()]

def build_system_prompt(agent_content: str | None, skills_text: str) -> str:
    if agent_content:
        base = f"# Especialista\n--- PROJETO ---\n{agent_content}\n"
    else:
        base = "Assistente técnico."
    return f"{base}\n\n{skills_text}"

async def _api_call_with_retry(client, *, model, max_tokens, system, messages, tools,
                               label: str = "IA",
                               max_overload_retries: int = 6):
    """
    Wraps stream call with exponential backoff on overloaded_error.
    Retorna (final_message, streamed_text, tool_calls).
    """
    for attempt in range(max_overload_retries + 1):
        try:
            stream_ctx = client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=tools,
            )
            return await stream_with_thinking(stream_ctx, label=label)
        except Exception as e:
            if "overloaded" in str(e).lower() and attempt < max_overload_retries:
                wait = min(120, 10 * (2 ** attempt))
                print(f"\n[⚠️ API sobrecarregada] Aguardando {wait}s... (tentativa {attempt + 1}/{max_overload_retries})")
                await asyncio.sleep(wait)
            else:
                raise


async def process_tool_call(tool, native_manager: NativeToolsManager,
                            mcp_manager: MCPManager, native_names: set[str]) -> dict:
    try:
        if tool.name in native_names:
            result = await native_manager.execute_tool(tool.name, tool.input)
        else:
            result = await mcp_manager.call_tool(tool.name, tool.input)
        return {"type": "tool_result", "tool_use_id": tool.id, "content": str(result)}
    except Exception as e:
        return {"type": "tool_result", "tool_use_id": tool.id,
                "content": f"Erro: {e}", "is_error": True}

def resolve_user_input(raw: str, command_manager: CommandManager) -> tuple[str, str | None, str | None]:
    if raw.startswith("/"):
        parts = raw[1:].split(maxsplit=1)
        cmd_name = parts[0]
        cmd_content = command_manager.get_commands(cmd_name)
        if cmd_content:
            model_override = _extract_model_tag(cmd_content)
            cmd_content_clean = re.sub(r"^@model:.*\n?", "", cmd_content, flags=re.MULTILINE).strip()
            rest = parts[1] if len(parts) > 1 else ""
            return f"{cmd_content_clean} {rest}".strip(), None, model_override
    return raw, None, None

def _extract_model_tag(content: str) -> str | None:
    match = re.search(r"^@model:\s*(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else None

def load_prompt_file(prompt_name: str) -> str | None:
    """Busca e lê um arquivo .md na pasta prompts pelo nome (sem extensão)."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, "prompts", f"{prompt_name}.md")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

style = Style.from_dict({
    'prompt': 'ansicyan bold',
})

# ── Cancelamento de loop da IA via Ctrl+C ou Backspace em buffer vazio ────────
# _ai_task aponta para a Task asyncio do loop de IA em curso.
# Cancelar essa task interrompe imediatamente qualquer await dentro dela
# (stream da API, asyncio.gather de tools, asyncio.sleep de retry).
_ai_task: asyncio.Task | None = None

def _build_key_bindings() -> KeyBindings:
    kb = KeyBindings()

    # ── Backspace normal: apaga caractere se o buffer tiver texto ─────────
    # Registra APENAS ControlH (que é o backspace real em Unix/macOS).
    # Registrar Keys.Backspace junto causa conflito de binding no prompt_toolkit
    # e faz o backspace parar de funcionar completamente.
    @kb.add("c-h")
    def _on_backspace(event):
        buf = event.app.current_buffer
        if buf.text:
            # Comportamento normal: apaga o caractere antes do cursor
            buf.delete_before_cursor()
        else:
            # Buffer vazio + IA processando → cancela a task imediatamente
            global _ai_task
            if _ai_task is not None and not _ai_task.done():
                _ai_task.cancel()
                # Imprime fora do contexto do prompt_toolkit para não corromper a UI
                event.app.exit()   # fecha o prompt em curso (se houver)

    # ── Ctrl+C durante o loop da IA: mesma ação de cancelamento ──────────
    @kb.add("c-c")
    def _on_ctrl_c(event):
        global _ai_task
        if _ai_task is not None and not _ai_task.done():
            _ai_task.cancel()
            event.app.exit()
        else:
            # Sem IA rodando → comportamento padrão (raise KeyboardInterrupt)
            raise KeyboardInterrupt

    return kb

_NATIVE_TOOL_NAMES: frozenset[str] = frozenset({
    "read_files", "shell_execute", "write_file", "patch_file", "list_dir", "search_text",
})


def _crew_needs_mcp(config_path: str) -> bool:
    """
    Lê o YAML da crew e verifica se algum agente declara ao menos uma tool
    que não é nativa. Se nenhum agente precisar de MCP, retorna False e o
    inicializador pode pular a conexão com os servidores MCP.
    """
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            import yaml as _yaml
            data = _yaml.safe_load(f)
        agents = data.get("crew", []) if isinstance(data, dict) else []
        for agent in agents:
            for tool in agent.get("tools", []):
                if tool not in _NATIVE_TOOL_NAMES:
                    return True
        return False
    except Exception:
        return True  # na dúvida, inicializa MCP normalmente


def _crew_required_mcps(config_path: str) -> list[str] | None:
    """
    Lê o YAML da crew e retorna a lista de prefixos de MCP que os agentes
    realmente utilizam (tools que não são nativas).
    Retorna None em caso de erro (fallback: carregar todos).
    """
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            import yaml as _yaml
            data = _yaml.safe_load(f)
        agents = data.get("crew", []) if isinstance(data, dict) else []
        needed: set[str] = set()
        for agent in agents:
            for tool in agent.get("tools", []):
                if tool not in _NATIVE_TOOL_NAMES:
                    needed.add(tool)
        return sorted(needed)
    except Exception:
        return None  # na dúvida, deixa o caller carregar todos


async def run_crew_headless(crew_name: str, sprint_path: str) -> None:
    """Executa uma crew diretamente via CLI sem entrar no loop interativo."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "crews", f"{crew_name}.yaml")

    if not os.path.exists(config_path):
        print(f"❌ Arquivo de crew não encontrado: {config_path}")
        return

    # sprint_path é passado como task para o orquestrador (equivale ao partes[2] do #crew)
    task_desc = sprint_path

    
    client = _build_client()
    mcp    = MCPManager()
    native = NativeToolsManager()

    required_mcps = _crew_required_mcps(config_path)  # lista de prefixos reais usados pelos agentes
    if required_mcps is not None and len(required_mcps) == 0:
        print("[⚡] Nenhum agente da crew usa MCP — iniciando sem servidores MCP")
    elif required_mcps is not None:
        print(f"[⚡] MCPs necessários para esta crew: {required_mcps}")

    try:
        if required_mcps is None or len(required_mcps) > 0:
            # None = erro ao ler YAML → carrega tudo por segurança
            # lista com itens → carrega só os MCPs listados
            await mcp.initialize_standard_servers(allowed=required_mcps)
        print(f"\n[🚀] Iniciando crew '{crew_name}' com sprint: {task_desc}")
        orc = Orquestrador(config_path, client, mcp, native, SkillManager(),
                           sprint_path=task_desc)
        await orc.run(task_desc)
    finally:
        await mcp.cleanup()


async def chat() -> None:
    session = PromptSession(history=FileHistory('.chat_history'), key_bindings=_build_key_bindings())
    parser = argparse.ArgumentParser()
    parser.add_argument("--skills",         type=str,  default=None)
    parser.add_argument("--mcps",           type=str,  default=None, help="MCPs a inicializar: \"[jira,bitbucket]\" ou \"[all]\" para todos. Sem este flag: nenhum MCP é carregado.")
    parser.add_argument("--crew",           type=str,  default=None, help="Nome da crew (sem extensão .yaml)")
    parser.add_argument("--sprint",         type=str,  default=None, help="Caminho completo do arquivo de sprint")
    parser.add_argument("--no-mcp",         action="store_true",     help="Desativa todos os MCP servers")
    parser.add_argument("--context-file",   type=str,  default=None, help="Arquivo de texto a injetar como primeira mensagem")
    parser.add_argument("--model-override", type=str,  default=None, help="Modelo a usar no lugar do MODEL_NAME padrão")
    parser.add_argument("--headless",       action="store_true",     help="Encerra após processar o contexto inicial (modo cron/batch)")
    parser.add_argument("--no-clear",       action="store_true",     help="Não limpa o console ao iniciar (preserva output anterior)")
    parser.add_argument("--no-usage",        action="store_true",     help="Oculta consumo de tokens e custo por ciclo (padrão: visível)")
    args, _ = parser.parse_known_args()

    # ── Modo headless: --crew + --sprint ──────────────────────────────────
    if args.crew and args.sprint:
        await run_crew_headless(args.crew, args.sprint)
        return

    selected_skills = (
        [s.strip() for s in args.skills.strip("[]").split(",") if s.strip()]
        if args.skills else None
    )

    # None     = --mcps não foi passado → sem MCPs (padrão)
    # ["all"]  = --mcps "[all]" → todos os MCPs disponíveis
    # [a, b]   = MCPs explicitamente selecionados via --mcps "[a,b]"
    # []       = --mcps passado mas vazio → sem MCPs
    if args.mcps:
        _raw = [m.strip() for m in args.mcps.strip("[]").split(",") if m.strip()]
        selected_mcps = None if _raw == ["all"] else _raw  # None → initialize_standard_servers carrega todos
    else:
        selected_mcps = []  # sem --mcps → nenhum MCP

    effective_model = args.model_override.strip() if args.model_override else MODEL_NAME

    client  = _build_client()
    mcp     = MCPManager()
    native  = NativeToolsManager()
    command = CommandManager()

    total_in = total_out = total_cache = 0
    total_cost = total_discount = 0.0

    try:
        if not args.no_clear:
            clear_console()
        set_terminal_title(effective_model)
        print_logo(effective_model)
        print(f"{BLUE_BOLD}  💡 Dica: ao mudar de assunto, digite {CYAN}/clear{BLUE_BOLD} para limpar o histórico e economizar tokens.{RESET}")
        print()
        # MCPs só inicializam se --mcps for passado explicitamente; --no-mcp também bloqueia
        # selected_mcps == []  → sem MCPs (padrão quando --mcps não é informado)
        # selected_mcps == None → todos (--mcps "[all]")
        # selected_mcps == [a,b] → apenas os listados
        if not args.no_mcp and selected_mcps != []:
            await mcp.initialize_standard_servers(allowed=selected_mcps)

        agent_content: str | None = None
        if is_project_root():
            answer = await asyncio.to_thread(input, "Carregar AGENT.md? (Y/n): ")
            if answer.lower() != "n":
                with open("agent.md", "r", encoding="utf-8") as f:
                    agent_content = f.read()

                # Detecta @Useful-Skills no agent.md e faz merge com --skills
                agent_skills = extract_agent_skills(agent_content)
                if agent_skills:
                    cli_skills = selected_skills or []
                    merged = cli_skills + [s for s in agent_skills if s not in cli_skills]
                    selected_skills = merged
                    print(f"{BLUE_BOLD}[agent.md] @Useful-Skills detectadas: {agent_skills}{RESET}")

        skills_text   = SkillManager().get_all_skills(selected_names=selected_skills)
        system_prompt = build_system_prompt(agent_content, skills_text)

        # ── Monta o conjunto de ferramentas ativas ──────────────────────────
        native_defs  = native.get_tools()
        native_names = {t["name"] for t in native_defs}
        # Todas as ferramentas nativas são expostas à IA
        active_tools = list(native_defs)
        if not args.no_mcp:
            active_tools += await mcp.get_all_tools()

        history: list[dict] = []

        # ── Contexto inicial via --context-file ────────────────────────────
        if args.context_file and os.path.exists(args.context_file):
            with open(args.context_file, "r", encoding="utf-8") as f:
                context_text = f.read()
            os.unlink(args.context_file)  # remove o temp após leitura
            history.append({"role": "user", "content": context_text})
            print(f"{BLUE_BOLD}[📋] Contexto carregado — processando...{RESET}")

    except Exception as e:
        print(f"{RED}[!] Falha na inicialização: {type(e).__name__}: {e}\n{traceback.format_exc()}{RESET}")
        return

    # Se há contexto pré-carregado, processa antes de pedir input
    _process_pending = bool(history)
    _headless = args.headless

    while True:
        try:
            if _process_pending:
                _process_pending = False
                # Pula direto para o ciclo de IA sem pedir input ao usuário
                user_input = None
            else:
                user_input = await session.prompt_async(
                    "\nVocê ➔ ",
                    style=style
                )

            if user_input is not None and not user_input:
                continue

            if user_input is None:
                # Contexto pré-carregado: processa o histórico já montado
                current_system = system_prompt
                current_model  = effective_model
            # ── #crew <config> <task> ──────────────────────────────────────
            elif user_input.startswith("#crew"):
                parts = user_input.split(maxsplit=2)
                config_file = parts[1]
                task_desc = parts[2] if len(parts) > 2 else ""

                base_dir = os.path.dirname(os.path.abspath(__file__))
                config_path = os.path.join(base_dir, "crews", f"{config_file}.yaml")
                if not os.path.exists(config_path):
                    print(f"❌ Erro: Arquivo de equipe não encontrado em: {config_path}")
                else:
                    crew_mcps = _crew_required_mcps(config_path)  # MCPs que esta crew precisa
                    if crew_mcps is not None and len(crew_mcps) == 0:
                        print("[⚡] Nenhum agente da crew usa MCP — executando sem MCPs")
                    else:
                        # Conecta apenas os MCPs que a crew precisa e ainda não estão ativos
                        missing = [m for m in (crew_mcps or []) if m not in mcp.sessions]
                        if missing:
                            print(f"[⚡] Conectando MCPs necessários para esta crew: {missing}")
                            await mcp.initialize_standard_servers(allowed=missing)
                        already = [m for m in (crew_mcps or []) if m in mcp.sessions]
                        if already:
                            print(f"[✅] MCPs já conectados reutilizados: {already}")
                    exec_id = uuid.uuid4().hex[:8]
                    print(f"\n[🚀] Iniciando equipe '{config_file}' — exec_id: {exec_id} — tarefa: {task_desc}")
                    orc = Orquestrador(config_path, client, mcp, native, SkillManager(),
                                      execution_id=exec_id, sprint_path=task_desc)
                    await orc.run(task_desc)
                continue

            # ── #prompt <nome-do-arquivo> ──────────────────────────────────
            elif user_input.startswith("#prompt"):
                parts = user_input.split(maxsplit=1)
                if len(parts) < 2 or not parts[1].strip():
                    print("❌ Uso: #prompt <nome-do-arquivo>")
                    continue

                prompt_name = parts[1].strip()
                prompt_content = load_prompt_file(prompt_name)
                if prompt_content is None:
                    base_dir = os.path.dirname(os.path.abspath(__file__))
                    print(f"❌ Prompt não encontrado: {os.path.join(base_dir, 'prompts', prompt_name + '.md')}")
                    continue

                print(f"\n[📄] Executando prompt: {prompt_name}.md")
                history.append({"role": "user", "content": prompt_content})
                current_system = system_prompt
                current_model = MODEL_NAME

            else:
                if user_input.lower() in {"sair", "exit", "quit"}:
                    break

                if user_input.strip() == "/clear":
                    history.clear()
                    print(f"\n{GREEN}[🧹] Histórico limpo — novo assunto, zero tokens de contexto.{RESET}")
                    continue

                user_text, system_override, model_override = resolve_user_input(user_input, command)
                current_system = system_override or system_prompt
                current_model  = model_override or MODEL_NAME
                if model_override:
                    set_terminal_title(current_model)
                    print_logo(current_model)
                    print(f"{BLUE_BOLD}[⚡] Modelo override: {model_override}{RESET}")
                history.append({"role": "user", "content": user_text})

            # Envolve o loop de ciclos numa Task cancelável.
            # Backspace (buffer vazio) ou Ctrl+C durante a IA cancela esta task
            # imediatamente, interrompendo qualquer await em curso (stream/tools).
            # Contadores mutáveis passados por lista para que a coroutine os atualize.
            counters = {
                "ciclo": 0,
                "empty_strikes": 0,
                "total_in":    total_in,
                "total_out":   total_out,
                "total_cache": total_cache,
                "total_cost":  total_cost,
                "total_discount": total_discount,
            }
            MAX_EMPTY_INPUT_STRIKES = 3

            async def _run_cycles() -> None:
                while True:
                    counters["ciclo"] += 1
                    print(f"\n[🔄 Ciclo {counters['ciclo']}] Consultando modelo...", flush=True)
                    resp, streamed_text, tool_calls = await _api_call_with_retry(
                        client,
                        model=current_model,
                        max_tokens=max_tokens_for(current_model),
                        system=[{"type": "text", "text": current_system,
                                 "cache_control": {"type": "ephemeral"}}],
                        messages=history,
                        tools=active_tools,
                        label="AI",
                    )

                    u       = resp.usage
                    c_in    = u.input_tokens
                    c_out   = u.output_tokens
                    c_cache = getattr(u, "cache_read_input_tokens", 0)

                    counters["total_in"]    += c_in
                    counters["total_out"]   += c_out
                    counters["total_cache"] += c_cache

                    call_cost     = (c_in * PRICE_IN) + (c_out * PRICE_OUT)
                    call_discount = c_cache * PRICE_CACHE
                    counters["total_cost"]     += call_cost
                    counters["total_discount"] += call_discount

                    print_usage(c_in, c_out, c_cache,
                                counters["total_in"], counters["total_out"], counters["total_cache"],
                                call_cost, counters["total_cost"], counters["total_discount"],
                                show=not args.no_usage)
                    set_terminal_title(current_model,
                                       counters["total_in"], counters["total_out"], counters["total_cache"])

                    blocks: list[dict] = []
                    for block in resp.content:
                        if block.type == "text":
                            blocks.append({"type": "text", "text": block.text})
                        elif block.type == "tool_use":
                            blocks.append({"type": "tool_use", "id": block.id,
                                           "name": block.name, "input": block.input})

                    history.append({"role": "assistant", "content": blocks})

                    if not tool_calls:
                        if resp.stop_reason == "max_tokens":
                            history.append({"role": "user", "content": "Continue."})
                            continue
                        if _headless:
                            print("\n[⏹] Modo headless — encerrando após resposta.", flush=True)
                            if not args.no_mcp:
                                await mcp.cleanup()
                            return
                        break

                    nomes_tools = ", ".join(t.name for t in tool_calls)
                    print(f"\n[🔧 Ciclo {counters['ciclo']}] Executando ferramentas: {nomes_tools}", flush=True)

                    valid_calls, empty_results = [], []
                    for t in tool_calls:
                        if not t.input or not isinstance(t.input, dict):
                            counters["empty_strikes"] += 1
                            print(f"  ⚠️  {t.name} input VAZIO — strike {counters['empty_strikes']}/{MAX_EMPTY_INPUT_STRIKES}")
                            if counters["empty_strikes"] >= MAX_EMPTY_INPUT_STRIKES:
                                print(f"  🛑 {MAX_EMPTY_INPUT_STRIKES} inputs vazios consecutivos — abortando ciclo para evitar loop infinito.")
                                history.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": t.id, "content": "❌ Loop abortado por excesso de inputs vazios. Reformule sua abordagem.", "is_error": True}]})
                                tool_calls = []
                                break
                            empty_results.append({
                                "type": "tool_result",
                                "tool_use_id": t.id,
                                "content": (
                                    f"❌ {t.name} bloqueado: input chegou vazio {{}}.\n"
                                    "   Reenvie a chamada com os parâmetros obrigatórios preenchidos.\n"
                                    f"   ⚠️  Strike {counters['empty_strikes']}/{MAX_EMPTY_INPUT_STRIKES} — após {MAX_EMPTY_INPUT_STRIKES} erros o ciclo será abortado."
                                ),
                                "is_error": True,
                            })
                        else:
                            valid_calls.append(t)

                    gathered = await asyncio.gather(
                        *[process_tool_call(t, native, mcp, native_names) for t in valid_calls]
                    )
                    if valid_calls:
                        counters["empty_strikes"] = 0
                    results = empty_results + list(gathered)
                    history.append({"role": "user", "content": list(results)})

            global _ai_task
            _ai_task = asyncio.ensure_future(_run_cycles())
            try:
                await _ai_task
            except asyncio.CancelledError:
                print(f"\n{RED}[⏸] Interrompido. Histórico preservado — continue digitando.{RESET}", flush=True)
            finally:
                _ai_task = None
                # Propaga contadores de volta para o escopo externo
                total_in       = counters["total_in"]
                total_out      = counters["total_out"]
                total_cache    = counters["total_cache"]
                total_cost     = counters["total_cost"]
                total_discount = counters["total_discount"]

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\n{RED}[!] Erro no loop: {type(e).__name__}: {e}")
            print(f"\n--- Traceback completo ---\n{traceback.format_exc()}---{RESET}")
            break

    if not args.no_mcp:
        await mcp.cleanup()

if __name__ == "__main__":
    asyncio.run(chat())
