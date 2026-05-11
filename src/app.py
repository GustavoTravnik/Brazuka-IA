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
import platform

if platform.system() == "Windows":
    from controllers.native_tools_windows import NativeToolsManager
else:
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

# Modelos do Gemini
MODEL_FREE      = os.getenv("MODEL_GEMINI", "gemini-1.5-flash")
MODEL_ROBUST    = os.getenv("MODEL_GEMINI_PRO", "gemini-1.5-pro")
MODEL_INTER     = os.getenv("MODEL_GEMINI_FLASH", "gemini-1.5-flash")

API_KEY         = os.getenv("GEMINI_API_KEY")
CONTEXTS_DIR    = "contexts"

if not os.path.exists(CONTEXTS_DIR):
    os.makedirs(CONTEXTS_DIR)

if not API_KEY:
    print("❌ Erro: GEMINI_API_KEY não encontrada no arquivo .env")
    sys.exit(1)

genai.configure(api_key=API_KEY, transport='rest')

# Mapeamento de nomes de ferramentas: gemini_safe_name -> original_name
tool_name_mapping = {}

def convert_tools_to_gemini(tools: list[dict]):
    """Converte definições de ferramentas do padrão Anthropic para o padrão Gemini."""
    if not tools: return []
    
    functions = []
    tool_name_mapping.clear()
    
    for t in tools:
        original_name = t["name"]
        # Gemini exige nomes que correspondam a [a-zA-Z0-9_-]+ (na verdade algumas versões são mais restritas, apenas underscores)
        # Vamos ser conservadores e trocar tudo que não for alfanumérico por underscore
        safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', original_name)
        tool_name_mapping[safe_name] = original_name
        
        # Garante que o schema tenha o formato correto para o Gemini
        schema = t.get("input_schema", {})
        if "type" not in schema:
            schema["type"] = "object"
            
        # Remove 'default' field from all properties in the schema
        if "properties" in schema:
            for prop_name, prop_details in schema["properties"].items():
                if "default" in prop_details:
                    del prop_details["default"]
            
        functions.append({
            "name": safe_name,
            "description": t["description"],
            "parameters": schema
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
                    # Usa o nome mapeado (seguro para o Gemini)
                    original_name = block["name"]
                    safe_name = next((k for k, v in tool_name_mapping.items() if v == original_name), original_name)
                    parts.append({
                        "function_call": {
                            "name": safe_name,
                            "args": block["input"]
                        }
                    })
                elif b_type == "tool_result":
                    tool_id = block.get("tool_use_id")
                    original_tool_name = tool_id_to_name.get(tool_id, tool_id)
                    # Usa o nome mapeado (seguro para o Gemini)
                    safe_name = next((k for k, v in tool_name_mapping.items() if v == original_tool_name), original_tool_name)
                    
                    res_val = block.get("content", "")
                    parts.append({
                        "function_response": {
                            "name": safe_name,
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
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=max_tokens,
                    temperature=0.0
                )
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
        # Se falhar por causa das ferramentas, tenta sem elas como fallback
        if tools and "tool" in str(e).lower():
            print("⚠️ Tentando novamente sem ferramentas...")
            return await _api_call_with_retry(model_instance, model=model, max_tokens=max_tokens, system=system, messages=messages, tools=None, label=label)
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
    parser.add_argument("model_name", type=str, nargs='?', choices=['free', 'robust', 'flash'], help="Modelo a usar (default: free)")
    parser.add_argument("--model", type=str, choices=['free', 'robust', 'flash'], default='free')
    parser.add_argument("--mcps", type=str, nargs='?', const='all', default=None, 
                        help="Carregar servidores MCP. Use --mcps para todos ou --mcps s1,s2 para específicos.")
    args, _ = parser.parse_known_args()

    model_map = {
        'free': MODEL_FREE,
        'robust': MODEL_ROBUST,
        'flash': MODEL_INTER
    }
    
    # Prioridade para o argumento posicional, se não, usa o flag --model
    current_model_key = args.model_name if args.model_name else args.model
    effective_model = model_map[current_model_key]
    
    def get_client(m_name):
        return genai.GenerativeModel(
            model_name=m_name,
            system_instruction="Você é o COIA, um assistente técnico avançado. Seu diretório de trabalho é onde o arquivo `app.py` está localizado. A pasta `skills` também está neste diretório. Use as ferramentas sempre que necessário para realizar tarefas no sistema."
        )

    client = get_client(effective_model)
    
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

            if user_input.startswith("/model"):
                parts = user_input.split()
                if len(parts) > 1 and parts[1] in model_map:
                    current_model_key = parts[1]
                    effective_model = model_map[current_model_key]
                    client = get_client(effective_model)
                    print(f"{GREEN}🔄 Modelo alterado para: {effective_model} ({current_model_key}){RESET}")
                else:
                    print(f"{RED}❌ Uso: /model [free|robust|flash]{RESET}")
                continue

            if user_input == "/clear":
                _save_history_to_contexts(history, "clear")
                history.clear()
                print(f"{GREEN}🧹 Histórico limpo.{RESET}")
                continue

            history.append({"role": "user", "content": user_input})
            tool_results = []

            while True:
                print(f"[🔄] Consultando Gemini ({effective_model})...")
                
                # Loosen tool routing: always send tools if it's not a very short conversation starter
                # Or just always send them since Gemini Flash is cheap.
                # Here we use a simpler check: if it's not a command and has more than 3 chars.
                send_tools = True if len(user_input) > 3 or tool_results else False
                tools_to_send = active_tools if send_tools else []
                
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
                    # Resolve o nome original da ferramenta a partir do nome seguro do Gemini
                    original_tool_name = tool_name_mapping.get(tc['name'], tc['name'])
                    print(f"[🔧] {original_tool_name}...")
                    
                    native_names = {t["name"] for t in native.get_tools()}
                    try:
                        if original_tool_name in native_names:
                            res = await native.execute_tool(original_tool_name, tc['input'])
                        else:
                            res = await mcp.call_tool(original_tool_name, tc['input'])
                    except Exception as te:
                        res = f"Error executing tool: {te}"
                        
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc['id'],
                        "content": str(res)
                    })
                
                history.append({"role": "user", "content": tool_results})
                user_input = "" # Clear user input for the next iteration of tool calls

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
