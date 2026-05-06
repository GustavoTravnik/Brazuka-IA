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

# Correção do nome do modelo (gemini-1.5-pro é o atual estável)
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

# --- FUNÇÕES DE UTILIDADE ---

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
    # Heurística simplificada para o exemplo
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

# --- NÚCLEO DE COMUNICAÇÃO GEMINI ---

def convert_history_to_gemini(history: list[dict]):
    """Converte histórico do padrão Anthropic/COIA para o padrão Gemini."""
    gemini_history = []
    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        content = msg["content"]
        # Simplifica conteúdos complexos para string para evitar erros de tipo no SDK
        if isinstance(content, list):
            text_parts = [block.get("text", "") for block in content if block.get("type") == "text"]
            content = " ".join(text_parts)
        gemini_history.append({"role": role, "parts": [content]})
    return gemini_history

async def _api_call_with_retry(model_instance, *, model=None, max_tokens=4096, system=None, messages=None, tools=None, label="AI"):
    """
    Assinatura corrigida para aceitar os argumentos nomeados (model, system, tools, etc)
    que o loop principal está enviando.
    """
    try:
        # Pega a última mensagem do histórico
        if not messages:
            return None, "Histórico vazio", []
            
        last_msg = messages[-1]["content"]
        
        # Se for lista (padrão Anthropic), extrai o texto
        if isinstance(last_msg, list):
            text_content = ""
            for block in last_msg:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_content += block.get("text", "")
            last_msg = text_content

        loop = asyncio.get_event_loop()
        
        # Executa a chamada síncrona em thread para evitar conflitos de gRPC no WSL
        def call_gemini():
            return model_instance.generate_content(
                last_msg,
                generation_config=genai.types.GenerationConfig(max_output_tokens=max_tokens)
            )

        response = await loop.run_in_executor(None, call_gemini)
        
        # Mock do objeto de resposta para manter compatibilidade com seu loop
        class MockResponse:
            def __init__(self, res):
                self.text = res.text
                self.usage = type('obj', (object,), {
                    'input_tokens': 0, 
                    'output_tokens': 0, 
                    'cache_read_input_tokens': 0
                })
        
        return MockResponse(response), response.text, []
        
    except Exception as e:
        print(f"❌ Erro na API Gemini: {e}")
        raise

# --- UI E CORES ---

CYAN, RED, GREEN, BLUE_BOLD, RESET = ("\033[96m", "\033[1;31m", "\033[1;32m", "\033[1;34m", "\033[0m")

def print_logo(model: str = ""):
    print(f"{CYAN}==========================================")
    print(f"       COIA AI CLI - MODO GEMINI")
    print(f"       MODELO: {model}")
    print(f"=========================================={RESET}\n")

# --- LOOP PRINCIPAL ---

async def chat() -> None:
    session = PromptSession(history=FileHistory('.chat_history'))
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-override", type=str, default=None)
    args, _ = parser.parse_known_args()

    effective_model = args.model_override or MODEL_NAME
    
    # Inicialização correta do Gemini
    client = genai.GenerativeModel(
        model_name=effective_model,
        system_instruction="Você é o COIA, um assistente técnico avançado."
    )
    
    native = NativeToolsManager()
    command = CommandManager()
    history: list[dict] = []

    print_logo(effective_model)

    while True:
        try:
            user_input = await session.prompt_async("\nVocê ➔ ", style=Style.from_dict({'prompt': 'ansicyan bold'}))
            
            if not user_input: continue
            if user_input.lower() in {"sair", "exit"}: break

            if user_input == "/clear":
                _save_history_to_contexts(history, "clear")
                history.clear()
                print(f"{GREEN}🧹 Histórico limpo.{RESET}")
                continue

            # Adiciona ao histórico (formato Anthropic interno)
            history.append({"role": "user", "content": user_input})

            print(f"[🔄] Consultando Gemini ({effective_model})...")
            
            # Chamada adaptada
            resp, text, tools = await _api_call_with_retry(
                client, model=effective_model, max_tokens=4096, 
                system="", messages=history, tools=[]
            )

            print(f"\n{GREEN}COIA ➔{RESET} {text}")
            
            # Salva resposta no histórico
            history.append({"role": "assistant", "content": text})

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