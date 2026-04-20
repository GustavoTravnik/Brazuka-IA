"""
CheckpointManager — persistência de estado de execução de crews.

Salva o history de cada agente em disco a cada ciclo do _execute_loop,
permitindo retomar execuções interrompidas (queda de internet, crash, etc.).

Arquivo gerado: executions/<execution_id>.checkpoint.json
Relatório final: executions/<execution_id>.context.md
"""

from __future__ import annotations

import json
import os
import yaml as _yaml
from datetime import datetime, timezone
from pathlib import Path

EXECUTIONS_DIR = Path(__file__).parent.parent / "executions"


class CheckpointManager:
    """
    Gerencia a persistência incremental do estado de uma execução de crew.

    Uso:
        cp = CheckpointManager(execution_id="abc123", crew_name="project-remaker-team", sprint_path="...")
        cp.save(agent_name="O Arquiteto", history=[...], current_agent="O Arquiteto")

    Retomada:
        state = CheckpointManager.load("abc123")
        if state:
            history = state["agents"]["O Arquiteto"]["history"]
            current_agent = state["current_agent"]
    """

    def __init__(self, execution_id: str, crew_name: str, sprint_path: str) -> None:
        self.execution_id = execution_id
        self.crew_name = crew_name
        self.sprint_path = sprint_path
        self._path = EXECUTIONS_DIR / f"{execution_id}.checkpoint.json"
        EXECUTIONS_DIR.mkdir(parents=True, exist_ok=True)

        # Inicializa o arquivo se ainda não existe
        if not self._path.exists():
            self._write({
                "execution_id": execution_id,
                "crew_name": crew_name,
                "sprint_path": sprint_path,
                "status": "running",
                "created_at": _now(),
                "updated_at": _now(),
                "current_agent": None,
                "agents": {},
            })

    # ── API pública ──────────────────────────────────────────────────────────

    def save(self, agent_name: str, history: list[dict], current_agent: str) -> None:
        """
        Persiste o history do agente atual e qual agente está ativo.
        Chamado após cada resposta do modelo (a cada ciclo do _execute_loop).
        """
        state = self._read()
        state["updated_at"] = _now()
        state["current_agent"] = current_agent

        if agent_name not in state["agents"]:
            state["agents"][agent_name] = {"history": [], "started_at": _now()}

        state["agents"][agent_name]["history"] = history
        state["agents"][agent_name]["updated_at"] = _now()

        self._write(state)

    def mark_agent_done(self, agent_name: str, result: str, next_agent: str | None = None) -> None:
        """
        Marca o agente como concluído com o resultado final.
        Se next_agent for fornecido, atualiza current_agent imediatamente
        para que um eventual crash entre agentes retome pelo agente correto.
        """
        state = self._read()
        if agent_name in state["agents"]:
            state["agents"][agent_name]["status"] = "done"
            state["agents"][agent_name]["result"] = result[:2000]
            state["agents"][agent_name]["finished_at"] = _now()
        if next_agent:
            state["current_agent"] = next_agent
        state["updated_at"] = _now()
        self._write(state)

    def mark_done(self) -> None:
        """Marca a execução inteira como concluída e gera o relatório de contexto em markdown."""
        state = self._read()
        state["status"] = "done"
        state["finished_at"] = _now()
        state["updated_at"] = _now()
        self._write(state)
        self._generate_context_report(state)

    def mark_failed(self, reason: str) -> None:
        """Marca a execução como falha — preserva o state para análise/retomada."""
        state = self._read()
        state["status"] = "failed"
        state["failure_reason"] = reason[:1000]
        state["updated_at"] = _now()
        self._write(state)

    def get_agent_history(self, agent_name: str) -> list[dict]:
        """Retorna o history salvo de um agente (lista vazia se não existe)."""
        state = self._read()
        return state.get("agents", {}).get(agent_name, {}).get("history", [])

    def get_current_agent(self) -> str | None:
        """Retorna o nome do último agente ativo registrado."""
        return self._read().get("current_agent")

    def is_resumable(self) -> bool:
        """True se a execução foi interrompida e pode ser retomada."""
        state = self._read()
        return state.get("status") == "running"

    # ── Métodos estáticos ────────────────────────────────────────────────────

    @staticmethod
    def load(execution_id: str) -> dict | None:
        """Carrega o state completo de um checkpoint. Retorna None se não existe."""
        path = EXECUTIONS_DIR / f"{execution_id}.checkpoint.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def find_resumable(crew_name: str, sprint_path: str) -> dict | None:
        """
        Busca o checkpoint mais recente de uma crew+sprint que pode ser retomado.
        Útil para oferecer retomada automática ao usuário.
        """
        if not EXECUTIONS_DIR.exists():
            return None

        candidates = []
        for f in EXECUTIONS_DIR.glob("*.checkpoint.json"):
            try:
                state = json.loads(f.read_text(encoding="utf-8"))
                if (
                    state.get("status") == "running"
                    and state.get("crew_name") == crew_name
                    and state.get("sprint_path") == sprint_path
                ):
                    candidates.append(state)
            except (json.JSONDecodeError, OSError):
                continue

        if not candidates:
            return None

        # Retorna o mais recente pelo updated_at
        return max(candidates, key=lambda s: s.get("updated_at", ""))

    # ── Internos ─────────────────────────────────────────────────────────────

    def _generate_context_report(self, state: dict) -> None:
        """Gera executions/<execution_id>.context.md com todo o contexto da execução."""
        lines: list[str] = []

        # ── Cabeçalho ────────────────────────────────────────────────────────
        lines.append(f"# Relatório de Execução — {state.get('crew_name', 'crew')}")
        lines.append("")
        lines.append("| Campo | Valor |")
        lines.append("|---|---|")
        lines.append(f"| Execution ID | `{state.get('execution_id', '?')}` |")
        lines.append(f"| Crew | `{state.get('crew_name', '?')}` |")
        lines.append(f"| Iniciado em | {state.get('created_at', '?')} |")
        lines.append(f"| Finalizado em | {state.get('finished_at', '?')} |")
        lines.append(f"| Status | {state.get('status', '?')} |")
        lines.append("")

        # ── Contexto da sprint ───────────────────────────────────────────────
        sprint_path = state.get("sprint_path", "")
        if sprint_path:
            lines.append("## Sprint")
            lines.append("")
            sprint_data = _load_sprint(sprint_path)
            if sprint_data:
                lines.append(f"**Título:** {sprint_data.get('title', '?')}")
                lines.append("")
                description = sprint_data.get("description", "")
                if description:
                    lines.append("**Descrição:**")
                    lines.append("")
                    lines.append(description)
                    lines.append("")
                tasks = sprint_data.get("tasks", [])
                if tasks:
                    lines.append("**Tarefas:**")
                    lines.append("")
                    for t in tasks:
                        status = t.get("status", "?")
                        title = t.get("title", "sem título")
                        lines.append(f"- [{status.upper()}] {title}")
                    lines.append("")
                updates = sprint_data.get("updates", [])
                if updates:
                    lines.append("**Updates registrados:**")
                    lines.append("")
                    for u in updates:
                        lines.append(f"- {u}")
                    lines.append("")
            else:
                lines.append(f"_(sprint não encontrada em `{sprint_path}`)_")
                lines.append("")

        # ── Seção por agente ─────────────────────────────────────────────────
        lines.append("## Agentes")
        lines.append("")
        for agent_name, agent_data in state.get("agents", {}).items():
            lines.extend(self._render_agent_section(agent_name, agent_data))

        # ── Escreve o arquivo ────────────────────────────────────────────────
        report_path = self._path.with_suffix(".context.md")
        report_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"[✓] Relatório de contexto gerado: {report_path}")

    def _render_agent_section(self, agent_name: str, agent_data: dict) -> list[str]:
        """Renderiza a seção de um agente: raciocínios, tools chamadas e resultado final."""
        lines: list[str] = []
        lines.append(f"### {agent_name}")
        lines.append("")

        result = agent_data.get("result", "")
        if result:
            lines.append("**Resultado final:**")
            lines.append("")
            lines.append(result)
            lines.append("")

        history = agent_data.get("history", [])
        if not history:
            return lines

        lines.append("**Histórico de execução:**")
        lines.append("")

        tool_index: dict[str, dict] = {}

        for msg in history:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "assistant":
                if isinstance(content, list):
                    for block in content:
                        btype = block.get("type", "")
                        if btype == "text":
                            text = block.get("text", "").strip()
                            if text:
                                lines.append(f"> {text}")
                                lines.append("")
                        elif btype == "tool_use":
                            tool_id = block.get("id", "")
                            tool_name = block.get("name", "")
                            tool_input = block.get("input", {})
                            input_summary = _summarize_input(tool_input)
                            tool_index[tool_id] = {"name": tool_name, "input": input_summary}
                            lines.append(f"🔧 **{tool_name}** `{input_summary}`")
                            lines.append("")
                elif isinstance(content, str) and content.strip():
                    lines.append(f"> {content.strip()}")
                    lines.append("")

            elif role == "user":
                if isinstance(content, list):
                    for block in content:
                        if block.get("type") == "tool_result":
                            tool_id = block.get("tool_use_id", "")
                            tool_info = tool_index.get(tool_id, {})
                            tool_name = tool_info.get("name", "?")
                            raw_result = str(block.get("content", ""))
                            result_preview = _truncate(raw_result, 300)
                            is_error = block.get("is_error", False)
                            icon = "❌" if is_error else "✅"
                            lines.append(f"<details><summary>{icon} Resultado de <code>{tool_name}</code></summary>")
                            lines.append("")
                            lines.append("```")
                            lines.append(result_preview)
                            lines.append("```")
                            lines.append("")
                            lines.append("</details>")
                            lines.append("")

        return lines

    def _read(self) -> dict:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, state: dict) -> None:
        # Escrita atômica: grava em .tmp e renomeia, evita arquivo corrompido em crash
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_sprint(sprint_path: str) -> dict | None:
    try:
        with open(sprint_path, "r", encoding="utf-8") as f:
            return _yaml.safe_load(f)
    except Exception:
        return None


def _summarize_input(tool_input: dict) -> str:
    if not tool_input:
        return "{}"
    raw = json.dumps(tool_input, ensure_ascii=False)
    return _truncate(raw, 120)


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"
