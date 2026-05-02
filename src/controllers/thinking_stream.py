"""
thinking_stream.py
──────────────────
Utilitário de streaming com feedback visual "ainda pensando".

Comportamento:
  1. Enquanto aguarda o primeiro token de texto → exibe spinner animado na mesma linha
  2. Assim que o primeiro token chega → limpa o spinner e começa a imprimir em tempo real
  3. Tool-use e blocos sem texto → spinner fica ativo até o modelo terminar

Exporta:
  stream_with_thinking(stream_ctx, label) -> FinalMessage
    stream_ctx : resultado de `client.messages.stream(...)` (AsyncMessageStream)
    label      : string exibida antes do spinner, ex: "Agente X"
"""

import sys
import asyncio
from datetime import datetime

# ── Cores ANSI ────────────────────────────────────────────────────────────────
CYAN      = "\033[96m"
YELLOW    = "\033[93m"
GREEN     = "\033[1;32m"
RESET     = "\033[0m"
BOLD      = "\033[1m"
DIM       = "\033[2m"
ERASE_LINE = "\r\033[2K"          # vai ao início da linha e apaga tudo

# Frames do spinner — estilo "braille" suave
_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Mensagens rotativas exibidas junto ao spinner
_THINKING_MSGS = [
    "pensando",
    "analisando",
    "processando",
    "raciocinando",
    "elaborando",
    "consultando",
    "verificando",
    "organizando ideias",
    "montando resposta",
    "avaliando contexto",
]


def _now() -> str:
    return datetime.now().strftime("%H:%M")


# Spinner só faz sentido em terminal interativo; em pipes/logs seria lixo
_IS_TTY = sys.stdout.isatty()


async def _spinner_task(label: str, stop_event: asyncio.Event, first_token_event: asyncio.Event) -> None:
    """
    Roda em background, imprimindo o spinner na linha atual.
    Para quando `stop_event` ou `first_token_event` é setado.
    Suprimido automaticamente quando stdout não é um TTY (daemon, pipe, log).
    """
    if not _IS_TTY:
        # Sem TTY: aguarda silenciosamente até o stop_event ser setado
        await stop_event.wait()
        return

    frame_idx  = 0
    msg_idx    = 0
    tick       = 0          # contador de frames para trocar a mensagem
    MSG_EVERY  = 18         # troca a mensagem a cada N frames (~2.7s a 150ms/frame)

    while not stop_event.is_set() and not first_token_event.is_set():
        frame = _SPINNER_FRAMES[frame_idx % len(_SPINNER_FRAMES)]
        msg   = _THINKING_MSGS[msg_idx % len(_THINKING_MSGS)]
        elapsed = tick * 0.15  # segundos decorridos (aprox.)

        sys.stdout.write(
            f"{ERASE_LINE}{DIM}[{_now()}]{RESET} "
            f"{YELLOW}{frame}{RESET} "
            f"{CYAN}{label}{RESET}{DIM} — {msg}...  {elapsed:.0f}s{RESET}"
        )
        sys.stdout.flush()

        await asyncio.sleep(0.15)
        frame_idx += 1
        tick      += 1

        if tick % MSG_EVERY == 0:
            msg_idx += 1

    # Limpa a linha do spinner antes de sair
    sys.stdout.write(ERASE_LINE)
    sys.stdout.flush()


async def stream_with_thinking(stream_ctx, label: str = "IA"):
    """
    Consome um AsyncMessageStream com feedback visual.

    Parâmetros
    ----------
    stream_ctx : context manager retornado por `client.messages.stream(...)`
    label      : nome exibido no spinner (ex: nome do agente)

    Retorna
    -------
    (final_message, collected_text, tool_calls_raw)
      final_message   : objeto Message completo (mesmo de get_final_message())
      collected_text  : str com todo o texto acumulado do modelo
      tool_calls_raw  : lista de objetos ToolUseBlock recebidos
    """
    stop_event        = asyncio.Event()
    first_token_event = asyncio.Event()

    spinner = asyncio.create_task(_spinner_task(label, stop_event, first_token_event))

    collected_text  = ""
    tool_calls_raw  = []
    first_text_seen = False

    try:
        async with stream_ctx as stream:
            async for event in stream:
                etype = type(event).__name__

                # ── Primeiro texto: cancela spinner, começa streaming ──────
                if etype == "RawContentBlockDeltaEvent":
                    delta = event.delta
                    dtype = type(delta).__name__

                    if dtype == "TextDelta" and delta.text:
                        if not first_text_seen:
                            first_text_seen = True
                            first_token_event.set()    # para o spinner
                            await asyncio.sleep(0)     # cede para o spinner limpar a linha
                            # Cabeçalho de início de resposta (só em TTY)
                            if _IS_TTY:
                                sys.stdout.write(f"{DIM}[{_now()}]{RESET} {GREEN}{label}{RESET} — ")
                                sys.stdout.flush()

                        if _IS_TTY:
                            sys.stdout.write(delta.text)
                            sys.stdout.flush()
                        collected_text += delta.text

            # Garante nova linha após o streaming de texto (só em TTY)
            if first_text_seen and _IS_TTY:
                sys.stdout.write("\n")
                sys.stdout.flush()

            try:
                final_message = await stream.get_final_message()
            except AssertionError:
                raise RuntimeError(
                    f"Stream encerrou sem produzir mensagem final. "
                    f"Verifique se o model ID '{label}' é válido e acessível via proxy."
                ) from None

    finally:
        stop_event.set()
        await asyncio.sleep(0)   # deixa o spinner limpar a linha
        try:
            await asyncio.wait_for(spinner, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            spinner.cancel()

    # Extrai tool_calls do final_message para manter compatibilidade com o caller
    for block in final_message.content:
        if block.type == "tool_use":
            tool_calls_raw.append(block)

    return final_message, collected_text, tool_calls_raw
ls_raw
