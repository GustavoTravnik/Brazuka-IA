import os
import re
import sys
import uuid
import asyncio
import argparse
from dotenv import load_dotenv

# SDK Estável
import google.generativeai as genai
from google.generativeai import types

from controllers.agent_orchestrator import Orquestrador
from controllers.command_manager import CommandManager
from controllers.skill_manager import SkillManager
from controllers.mcp_manager import MCPManager
from controllers.native_tools import NativeToolsManager
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.keys import Keys
from prompt_toolkit.key_binding import KeyBindings

load_dotenv()

# Configurações do Gemini AI Studio
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

    async def get_final_message(self):
        # 1. Garantir o nome do modelo com prefixo correto para evitar 404
        full_model_name = self.model_name if self.model_name.startswith("models/") else f"models/{self.model_name}"

        # 2. Converter Tools para o formato do SDK Estável
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

        # 3. Extrair System Instruction
        system_text = ""
        if isinstance(self.system, list):
            for s in self.system:
                if s.get("type") == "text":
                    system_text += s.get("text", "") + "\n"
        elif isinstance(self.system, str):
            system_text = self.system

        # 4. Inicializar Modelo
        model = genai.GenerativeModel(
            model_name=full_model_name,
            system_instruction=system_text if system_text else None,
            tools=google_tools if google_tools else None
        )

        # 5. Converter Histórico de Mensagens para o formato Google
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
                        # Busca o nome da ferramenta original para o Google parear o resultado
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

        # 6. Execução Assíncrona (Resolvendo o erro de 'can't be used in await')
        # Usamos to_thread para rodar o método síncrono do SDK sem bloquear o loop
        response = await asyncio.to_thread(
            model.generate_content,
            contents=google_contents,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=self.max_tokens,
                temperature=0.0
            )
        )

        # 7. Parse da Resposta
        content_blocks = []
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.text:
                    content_blocks.append(DummyBlock(type="text", text=part.text))
                elif part.function_call:
                    call_id = f"call_{uuid.uuid4().hex[:8]}"
                    # Converte o objeto de argumentos para um dicionário Python
                    args = {k: v for k, v in part.function_call.args.items()}
                    content_blocks.append(DummyBlock(
                        type="tool_use",
                        id=call_id,
                        name=part.function_call.name,
                        input=args
                    ))

        # 8. Metadados de Uso
        usage_md = response.usage_metadata
        usage = DummyUsage(
            input_tokens=usage_md.prompt_token_count,
            output_tokens=usage_md.candidates_token_count,
            cache_read_input_tokens=getattr(usage_md, "cached_content_token_count", 0)
        )

        # 9. Stop Reason
        stop_reason = "end_turn"
        finish_reason = response.candidates[0].finish_reason if response.candidates else None
        # No SDK estável, finish_reason é um enum (1=STOP, 2=MAX_TOKENS)
        if finish_reason == 2:
            stop_reason = "max_tokens"

        return DummyResponse(content=content_blocks, usage=usage, stop_reason=stop_reason)

class DummyMessages:
    def stream(self, model, max_tokens, system, messages, tools):
        return DummyStream(model, max_tokens, system, messages, tools)

class AsyncAnthropicMock:
    def __init__(self):
        self.messages = DummyMessages()

def _build_client() -> AsyncAnthropicMock:
    return AsyncAnthropicMock()

# --- Funções de UI e Auxiliares ---

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
    f"    =========================================={RESET}",
]

def set_terminal_title(model: str) -> None:
    sys.stdout.write(f"\033]0;COIA — {model}\007")
    sys.stdout.flush()

def clear_console() -> None:
    os.system("cls" if os.name == "nt" else "clear")

def print_logo(model: str = "") -> None:
    print()
    for line in LOGO_LINES: print(line)
    if model:
        print(f"{BLUE_BOLD}    {model.center(40)}{RESET}")
    print(f"{CYAN}{BOLD}    {'=' * 40}{RESET}\n")

def print_usage(c_in, c_out, c_cache, t_in, t_out, t_cache, call_cost, total_cost, total_discount):
    print(
        f"{RED}\r [Tokens: {c_in} | {c_out} | Cache: {c_cache}]\n"
        f" [Total: {t_in} | {t_out} | R${total_cost:.4f}]{RESET}"
    )

def is_project_root() -> bool: return os.path.exists("agent.md")

def extract_agent_skills(content: str) -> list[str]:
    match = re.search(r"@Useful-Skills\s*=\s*\[?([^\]\n]+?)\]?\s*$", content, re.MULTILINE)
    return [s.strip() for s in match.group(1).split(",") if s.strip()] if match else []

PERF_RULES = (
    "\n## PERFORMANCE:\n"
    "1. Use raciocínio nativo.\n2. Leitura em lote.\n3. Não releia o que já sabe.\n"
)

def build_system_prompt(agent_content, skills_text):
    base = f"# Especialista\n{PERF_RULES}\n--- PROJETO ---\n{agent_content}\n" if agent_content else f"Assistente.\n{PERF_RULES}"
    return f"{base}\n\n{skills_text}"

async def _api_call_with_retry(client, **kwargs):
    for attempt in range(6):
        try:
            # O SDK estável não usa context manager 'async with' para chamadas simples
            # Mas nossa estrutura Mock simula isso
            async with client.messages.stream(**kwargs) as stream:
                return await stream.get_final_message()
        except Exception as e:
            if "429" in str(e) or "overloaded" in str(e).lower():
                wait = 10 * (2 ** attempt)
                print(f"\n[⚠️ Re-tentando em {wait}s...]")
                await asyncio.sleep(wait)
            else: raise

async def process_tool_call(tool, native, mcp, native_names):
    try:
        res = await native.execute_tool(tool.name, tool.input) if tool.name in native_names else await mcp.call_tool(tool.name, tool.input)
        return {"type": "tool_result", "tool_use_id": tool.id, "content": str(res)}
    except Exception as e:
        return {"type": "tool_result", "tool_use_id": tool.id, "content": f"Erro: {e}", "is_error": True}

def resolve_user_input(raw, command):
    if raw.startswith("/"):
        parts = raw[1:].split(maxsplit=1)
        content = command.get_commands(parts[0])
        if content:
            m_override = re.search(r"^@model:\s*(.+)$", content, re.MULTILINE)
            clean = re.sub(r"^@model:.*\n?", "", content, flags=re.MULTILINE).strip()
            return f"{clean} {parts[1] if len(parts)>1 else ''}".strip(), None, (m_override.group(1).strip() if m_override else None)
    return raw, None, None

def load_prompt_file(name):
    path = os.path.join(os.path.dirname(__file__), "prompts", f"{name}.md")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f: return f.read()
    return None

# --- Main Loop ---

async def chat() -> None:
    global _ai_processing, _cancel_event
    _cancel_event = asyncio.Event()
    
    session = PromptSession(history=FileHistory('.chat_history'))
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-override", type=str, default=None)
    args, _ = parser.parse_known_args()

    effective_model = args.model_override or MODEL_NAME
    client  = _build_client()
    mcp, native, command = MCPManager(), NativeToolsManager(), CommandManager()
    
    total_in = total_out = total_cache = total_cost = 0.0
    clear_console()
    print_logo(effective_model)
    set_terminal_title(effective_model)

    agent_content = None
    if is_project_root():
        if (await asyncio.to_thread(input, "Carregar agent.md? (Y/n): ")).lower() != "n":
            with open("agent.md", "r", encoding="utf-8") as f: agent_content = f.read()

    system_prompt = build_system_prompt(agent_content, SkillManager().get_all_skills())
    active_tools = list(native.get_tools())
    native_names = {t["name"] for t in active_tools}
    history = []

    while True:
        try:
            user_input = await session.prompt_async("\nVocê ➔ ", style=Style.from_dict({'prompt': 'ansicyan bold'}))
            if not user_input: continue
            if user_input.lower() in ["exit", "quit"]: break

            text, sys_ov, mod_ov = resolve_user_input(user_input, command)
            curr_model = mod_ov or effective_model
            history.append({"role": "user", "content": text})

            _ai_processing = True
            while True:
                if _cancel_event.is_set(): _cancel_event.clear(); break

                print(f"\n[🔄] Consultando {curr_model}...")
                resp = await _api_call_with_retry(
                    client, model=curr_model, max_tokens=max_tokens_for(curr_model),
                    system=sys_ov or system_prompt, messages=history, tools=active_tools
                )

                total_in += resp.usage.input_tokens
                total_out += resp.usage.output_tokens
                total_cost += (resp.usage.input_tokens * PRICE_IN) + (resp.usage.output_tokens * PRICE_OUT)
                
                print_usage(resp.usage.input_tokens, resp.usage.output_tokens, 0, total_in, total_out, 0, 0, total_cost, 0)

                blocks, tool_calls = [], []
                for b in resp.content:
                    if b.type == "text":
                        print(f"\nAI: {b.text}"); blocks.append({"type": "text", "text": b.text})
                    else:
                        blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                        tool_calls.append(b)
                
                history.append({"role": "assistant", "content": blocks})
                if not tool_calls: break

                print(f"[🔧] Executando: {', '.join(t.name for t in tool_calls)}")
                results = await asyncio.gather(*[process_tool_call(t, native, mcp, native_names) for t in tool_calls])
                history.append({"role": "user", "content": list(results)})

            _ai_processing = False
        except KeyboardInterrupt: break
        except Exception as e: print(f"❌ Erro: {e}")

if __name__ == "__main__":
    asyncio.run(chat())