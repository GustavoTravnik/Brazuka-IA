"""
token_logger.py
───────────────
Grava um arquivo .md em src/logs/ para cada sessão do COIA.

Objetivo: entender por que operações simples consomem muitos tokens de saída.
Cada turno registra:
  - Pergunta do usuário
  - Ferramentas chamadas (nome + input resumido)
  - Resposta do modelo (texto completo)
  - Contagem de tokens: entrada / saída / cache / cache_criado
  - Custo estimado do turno

Uso:
    from controllers.token_logger import TokenLogger

    logger = TokenLogger()          # cria o arquivo .md ao instanciar
    logger.log_turn(...)            # chama após cada ciclo de resposta
    logger.close()                  # grava rodapé com totais da sessão
"""

import os
from datetime import datetime
from typing import Optional

_HERE      = os.path.dirname(os.path.abspath(__file__))
_LOGS_DIR  = os.path.join(_HERE, "..", "logs")

def _logs_dir() -> str:
    os.makedirs(_LOGS_DIR, exist_ok=True)
    return _LOGS_DIR

def _sanitize(text: str, max_chars: int = 8_000) -> str:
    """Escapa backticks triplos para não quebrar o markdown e trunca se gigante."""
    text = text.replace("```", "‵‵‵")                           
    if len(text) > max_chars:
        half = max_chars // 2
        text = text[:half] + f"\n\n…[truncado — {len(text)} chars no total]…\n\n" + text[-half:]
    return text

class TokenLogger:
    """
    Instância por sessão do COIA.
    Cada turno = 1 chamada ao modelo (podendo conter N ciclos de tool calls).
    """

    def __init__(self, model: str = "desconhecido"):
        self.model    = model
        self.session  = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path     = os.path.join(_logs_dir(), f"tokens_{self.session}.md")
        self._turn    = 0
        self._totals  = {
            "in": 0, "out": 0,
            "cache_read": 0, "cache_created": 0,
            "cost": 0.0, "discount": 0.0,
        }
        self._start   = datetime.now()
        self._write_header()

    def _append(self, text: str) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(text)

    def _write_header(self) -> None:
        ts = self._start.strftime("%d/%m/%Y %H:%M:%S")
        self._append(
            f"# 📊 Log de Tokens — COIA\n\n"
            f"| Campo | Valor |\n"
            f"|-------|-------|\n"
            f"| **Sessão** | `{self.session}` |\n"
            f"| **Modelo** | `{self.model}` |\n"
            f"| **Início** | {ts} |\n"
            f"| **Arquivo** | `{os.path.basename(self.path)}` |\n\n"
            f"---\n\n"
        )

    def log_turn(
        self,
        *,
        user_input: str,
        model_output: str,
        tool_calls: list,                                               
        tokens_in: int,
        tokens_out: int,
        tokens_cache_read: int     = 0,
        tokens_cache_created: int  = 0,
        call_cost: float           = 0.0,
        call_discount: float       = 0.0,
        ciclo: int                 = 1,
        stop_reason: str           = "",
        model_used: str            = "",
        routing_label: str         = "",
    ) -> None:
        """Registra um turno completo (1 resposta do modelo, com ou sem tools)."""

        self._turn += 1
        self._totals["in"]            += tokens_in
        self._totals["out"]           += tokens_out
        self._totals["cache_read"]    += tokens_cache_read
        self._totals["cache_created"] += tokens_cache_created
        self._totals["cost"]          += call_cost
        self._totals["discount"]      += call_discount

        ts      = datetime.now().strftime("%H:%M:%S")
        model_u = model_used or self.model

        block  = f"## Turno {self._turn} — {ts}\n\n"

        block += (
            f"### Tokens\n\n"
            f"| Métrica | Este turno | Acumulado sessão |\n"
            f"|---------|:----------:|:-----------------:|\n"
            f"| 🟢 Entrada (input) | `{tokens_in:,}` | `{self._totals['in']:,}` |\n"
            f"| 🔴 **Saída (output)** | `{tokens_out:,}` | `{self._totals['out']:,}` |\n"
            f"| 🔵 Cache lido | `{tokens_cache_read:,}` | `{self._totals['cache_read']:,}` |\n"
            f"| 🟡 Cache criado | `{tokens_cache_created:,}` | `{self._totals['cache_created']:,}` |\n"
            f"| 💰 Custo turno | R$ `{call_cost:.4f}` | R$ `{self._totals['cost']:.4f}` |\n"
            f"| 💚 Desconto cache | R$ `{call_discount:.4f}` | R$ `{self._totals['discount']:.4f}` |\n\n"
        )

        block += (
            f"**Modelo:** `{model_u}` | "
            f"**Ciclo:** `{ciclo}` | "
            f"**Stop reason:** `{stop_reason}` | "
            f"**Routing:** `{routing_label}`\n\n"
        )

        if tokens_in > 0:
            ratio = tokens_out / tokens_in * 100
            alerta = " ⚠️ **ALTO**" if ratio > 30 else ""
            block += f"**Ratio saída/entrada:** `{ratio:.1f}%`{alerta}\n\n"

        if tool_calls:
            block += f"### Ferramentas chamadas ({len(tool_calls)})\n\n"
            for i, t in enumerate(tool_calls, 1):
                name  = getattr(t, "name",  str(t))
                inp   = getattr(t, "input", {})
                inp_lines = []
                for k, v in (inp.items() if isinstance(inp, dict) else {}.items()):
                    v_str = str(v)
                    if len(v_str) > 200:
                        v_str = v_str[:200] + "…"
                    inp_lines.append(f"  - `{k}`: {v_str}")
                inp_md = "\n".join(inp_lines) if inp_lines else "  *(sem input)*"
                block += f"**{i}. `{name}`**\n{inp_md}\n\n"
        else:
            block += "_Sem ferramentas neste turno._\n\n"

        block += f"### Mensagem do usuário\n\n"
        block += f"```\n{_sanitize(user_input, 2_000)}\n```\n\n"

        block += f"### Resposta do modelo\n\n"
        if model_output.strip():
            block += f"```\n{_sanitize(model_output, 6_000)}\n```\n\n"
        elif tool_calls:
            block += "_[Resposta sem texto — o modelo executou apenas tool calls:]_\n\n"
            for i, t in enumerate(tool_calls, 1):
                name = getattr(t, "name", str(t))
                inp  = getattr(t, "input", {})
                inp_lines = []
                for k, v in (inp.items() if isinstance(inp, dict) else {}.items()):
                    v_str = str(v)
                    if len(v_str) > 300:
                        v_str = v_str[:300] + "…"
                    inp_lines.append(f"  - `{k}`: {v_str}")
                inp_md = "\n".join(inp_lines) if inp_lines else "  *(sem parâmetros)*"
                block += f"**{i}. `{name}`**\n{inp_md}\n\n"
        else:
            block += "_[Resposta completamente vazia — sem texto nem tool calls]_\n\n"

        block += "---\n\n"

        self._append(block)

    def close(self) -> None:
        """Grava o rodapé com totais da sessão."""
        elapsed = datetime.now() - self._start
        mins, secs = divmod(int(elapsed.total_seconds()), 60)

        footer = (
            f"## 📋 Resumo da Sessão\n\n"
            f"| Métrica | Total |\n"
            f"|---------|-------|\n"
            f"| Turnos | `{self._turn}` |\n"
            f"| Duração | `{mins}m {secs}s` |\n"
            f"| Tokens entrada | `{self._totals['in']:,}` |\n"
            f"| **Tokens saída** | `{self._totals['out']:,}` |\n"
            f"| Tokens cache (lido) | `{self._totals['cache_read']:,}` |\n"
            f"| Tokens cache (criado) | `{self._totals['cache_created']:,}` |\n"
            f"| Custo total | R$ `{self._totals['cost']:.4f}` |\n"
            f"| Desconto cache | R$ `{self._totals['discount']:.4f}` |\n\n"
            f"_Sessão encerrada em {datetime.now().strftime('%H:%M:%S')}_\n"
        )
        self._append(footer)
        print(f"\n[📝] Log de tokens salvo em: logs/{os.path.basename(self.path)}")
