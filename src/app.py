from anthropic import AsyncAnthropic, AsyncAnthropicVertex
import os
import re
import sys
import json
import uuid
import asyncio
import traceback
import argparse
import google.generativeai as genai
from google.generativeai import types
from datetime import datetime
from dotenv import load_dotenv
from controllers.agent_orchestrator import Orquestrador
from controllers.command_manager import CommandManager
from controllers.skill_manager import SkillManager
from controllers.mcp_manager import MCPManager
from controllers.native_tools import NativeToolsManager
from controllers.tool_router import needs_tools
from controllers.thinking_stream import stream_with_thinking
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.key_binding import KeyBindings

load_dotenv()

import subprocess as _subprocess
import time as _time

MODEL_NAME  = os.getenv("MODEL_GEMINI", "gemini-1.5-pro")
API_KEY     = os.getenv("GEMINI_API_KEY")
CONTEXTS_DIR = "contexts"

if not os.path.exists(CONTEXTS_DIR):
    os.makedirs(CONTEXTS_DIR)

if not API_KEY:
    print("❌ Erro: GEMINI_API_KEY não encontrada no arquivo .env")
    sys.exit(1)

genai.configure(api_key=API_KEY, transport='rest')

_COMPACT_SYSTEM_PROMPT = """\
Summarize the conversation as structured bullet notes. Max 20% of original size.
Skip: greetings, repetitions, tool outputs, file contents."""

def _estimate_msg_chars(msg: dict) -> int:
    content = msg.get("content", "")
    if isinstance(content, str): return len(content)
    return len(str(content))

def _extract_text_from_history(history: list[dict]) -> str:
    lines = []
    for msg in history:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        lines.append(f"[{role}]: {str(content)[:2000]}")
    return "\n".join(lines)

def _extract_user_keywords(text: str) -> set[str]:
    words = re.findall(r'[a-záàâãéèêíïóôõúüçñ]{4,}', text.lower())
    return {w for w in words if len(w) > 3}

def _detect_topic_change(history: list[dict], new_message: str, threshold: float = 0.15) -> bool:
    if len(history) < 6: return False
    new_keywords = _extract_user_keywords(new_message)
    if not new_keywords: return False
    return False 

def _save_history_to_contexts(history: list[dict], reason: str = "compact") -> str | None:
    if not history: return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(CONTEXTS_DIR, f"{ts}_{reason}.json")
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2, default=str)
        return filepath
    except Exception as e:
        print(f"[⚠️ Erro ao salvar contexto: {e}]")
        return None

def convert_tools_to_gemini(tools: list[dict]):
    """Converte definições de ferramentas do padrão Anthropic para o padrão Gemini."""
    if not tools: return []
    
    functions = []
    for t in tools:
        functions.append({
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"]
        })
    return [{"function_declarations": functions}]

def convert_history_to_gemini(history: list[dict]):
    """Converte histórico do padrão Anthropic/COIA para o padrão Gemini."""
    gemini_history = []
    
    tool_id_to_name = {}
    for msg in history:
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_use":
                    tool_id_to_name[block["id"]] = block["name"]

    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        content = msg["content"]
        parts = []

        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                b_type = block.get("type")
                if b_type == "text":
                    parts.append(block.get("text", ""))
                elif b_type == "tool_use":
                    parts.append({
                        "function_call": {
                            "name": block["name"],
                            "args": block["input"]
                        }
                    })
                elif b_type == "tool_result":
                    tool_id = block.get("tool_use_id")
                    tool_name = tool_id_to_name.get(tool_id, tool_id)
                    
                    res_val = block.get("content", "")
                    try:
                        if isinstance(res_val, str) and (res_val.startswith("{") or res_val.startswith("[")):
                            res_val = json.loads(res_val)
                    except: pass
                    
                    parts.append({
                        "function_response": {
                            "name": tool_name,
                            "response": {"result": res_val}
                        }
                    })
        
        if parts:
            gemini_history.append({"role": role, "parts": parts})
            
    return gemini_history

async def _api_call_with_retry(model_instance, *, model=None, max_tokens=4096, system=None, messages=None, tools=None, label="AI"):
    """
    Executa a chamada ao Gemini com suporte a histórico completo e ferramentas.
    """
    try:
        if not messages:
            return None, "Histórico vazio", []

        gemini_history = convert_history_to_gemini(messages)
        gemini_tools = convert_tools_to_gemini(tools) if tools else None

        loop = asyncio.get_event_loop()
        
        def call_gemini():
            return model_instance.generate_content(
                contents=gemini_history,
                tools=gemini_tools,
                generation_config=genai.types.GenerationConfig(max_output_tokens=max_tokens)
            )

        response = await loop.run_in_executor(None, call_gemini)
        
        text_parts = []
        tool_calls = []
        
        if response.candidates:
            part_list = response.candidates[0].content.parts
            for p in part_list:
                if p.text:
                    text_parts.append(p.text)
                if p.function_call:
                    tool_calls.append({
                        'id': f"call_{uuid.uuid4().hex[:8]}",
                        'name': p.function_call.name,
                        'input': dict(p.function_call.args)
                    })
        
        full_text = "".join(text_parts)
        
        class MockResponse:
            def __init__(self, res, txt, tcs):
                self.text = txt
                self.content = []
                if txt: self.content.append({'type': 'text', 'text': txt})
                for tc in tcs:
                    self.content.append({
                        'type': 'tool_use', 'id': tc['id'], 'name': tc['name'], 'input': tc['input']
                    })
                self.usage = type('obj', (object,), {
                    'input_tokens': 0, 
                    'output_tokens': 0, 
                    'cache_read_input_tokens': 0
                })
        
        return MockResponse(response, full_text, tool_calls), full_text, tool_calls
        
    except Exception as e:
        print(f"❌ Erro na API Gemini: {e}")
        raise

CYAN, RED, GREEN, BLUE_BOLD, RESET = ("\033[96m", "\033[1;31m", "\033[1;32m", "\033[1;34m", "\033[0m")

def print_logo(model: str = ""):
    print(f"{CYAN}==========================================")
    print(f"       COIA AI CLI - MODO GEMINI")
    print(f"       MODELO: {model}")
    print(f"=========================================={RESET}\n")

async def chat() -> None:
    session = PromptSession(history=FileHistory('.chat_history'))
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-override", type=str, default=None)
    parser.add_argument("--mcps", type=str, nargs='?', const='all', default=None, 
                        help="Carregar servidores MCP. Use --mcps para todos ou --mcps s1,s2 para específicos.")
    args, _ = parser.parse_known_args()

    effective_model = args.model_override or MODEL_NAME
    
    client = genai.GenerativeModel(
        model_name=effective_model,
        system_instruction="Você é o COIA, um assistente técnico avançado."
    )
    
    native = NativeToolsManager()
    mcp = MCPManager()
    
    if args.mcps:
        allowed = None if args.mcps == 'all' else args.mcps.split(',')
        await mcp.initialize_standard_servers(allowed=allowed)
    
    command = CommandManager()
    history: list[dict] = []

    print_logo(effective_model)

    while True:
        try:
            mcp_tools = await mcp.get_all_tools()
            active_tools = native.get_tools() + mcp_tools
            
            user_input = await session.prompt_async("\nVocê ➔ ", style=Style.from_dict({'prompt': 'ansicyan bold'}))
            
            if not user_input: continue
            if user_input.lower() in {"sair", "exit"}: break

            if user_input == "/clear":
                _save_history_to_contexts(history, "clear")
                history.clear()
                print(f"{GREEN}🧹 Histórico limpo.{RESET}")
                continue

            history.append({"role": "user", "content": user_input})

            while True:
                print(f"[🔄] Consultando Gemini ({effective_model})...")
                
                tools_to_send = active_tools if needs_tools(user_input, history) else []
                
                resp, text, tool_calls = await _api_call_with_retry(
                    client, model=effective_model, max_tokens=4096, 
                    system="", messages=history, tools=tools_to_send
                )

                history.append({"role": "assistant", "content": resp.content})

                if text:
                    print(f"\n{GREEN}COIA ➔{RESET} {text}")
                
                if not tool_calls:
                    break

                tool_results = []
                for tc in tool_calls:
                    print(f"[🔧] {tc['name']}...")
                    
                    native_names = {t["name"] for t in native.get_tools()}
                    if tc['name'] in native_names:
                        res = await native.execute_tool(tc['name'], tc['input'])
                    else:
                        res = await mcp.call_tool(tc['name'], tc['input'])
                        
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc['id'],
                        "content": str(res)
                    })
                
                history.append({"role": "user", "content": tool_results})
                user_input = "" 

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"{RED}![Erro]: {e}{RESET}")
            traceback.print_exc()

if __name__ == "__main__":
    try:
        asyncio.run(chat())
    except KeyboardInterrupt:
        pass
