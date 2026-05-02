"""
crew.py
───────
Orquestra a execução sequencial de agentes em uma sprint.

Correções aplicadas (v2):
  1. RateLimiter — cadência controlada por modelo para evitar suspend de conta
  2. Roteamento direto — bypass do roteador semântico quando o Gerente tem
     sprint_path: lê o YAML e decide o próximo agente deterministicamente,
     sem gastar uma chamada extra por turno
  3. Skills sob demanda — campo `on_demand_skills` no agente: skills pesadas
     (ex: META-github-repos-map, ~18K tokens) ficam fora do system prompt e
     são injetadas no context_prompt apenas quando a crew as declara como
     necessárias para aquele turno específico
  4. Sprint path explícito — o path da sprint viaja em todas as mensagens de
     context_prompt entre agentes, garantindo que o Gerente sempre leia o
     arquivo correto mesmo com clean_context=true
  5. Resumo de sprint no context_prompt — em vez de re-ler 95KB do YAML via
     tool call, o Gerente recebe um resumo compacto do estado atual das tarefas
     diretamente no context_prompt (zero tool calls adicionais)
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
import yaml as _yaml
from datetime import datetime
from services.semantic_router import SemanticRouter
from services.checkpoint import CheckpointManager
from services.rate_limiter import RateLimiter
from controllers.thinking_stream import stream_with_thinking


class FatalAPIError(Exception):
    """
    Erro não-recuperável da API.
    Ao ser levantado, crew.run() para imediatamente.
    """


_MODEL_MAX_TOKENS: dict[str, int] = {
    "gemini-1.5-pro":   32_000,
    "gemini-1.5-flash": 16_000,
}


def _max_tokens_for(model: str) -> int:
    return _MODEL_MAX_TOKENS.get(model, 16_000)


def _log(agent_name: str, action: str, model_id: str = "") -> None:
    ts = datetime.now().strftime("%H:%M")
    model_short = _short_model(model_id)
    suffix = f" - {model_short}" if model_short else ""
    print(f"[{ts}] - {agent_name} - {action}{suffix}", flush=True)


def _short_model(model_id: str) -> str:
    aliases = {
        "gemini-1.5-flash": "Flash",
        "gemini-1.5-pro":   "Pro",
    }
    if not model_id:
        return ""
    for key, alias in aliases.items():
        if key in model_id:
            return alias
    return model_id.split("-")[1].capitalize() if "-" in model_id else model_id


def _sprint_summary(sprint_path: str) -> str:
    """
    Lê o YAML da sprint e devolve um resumo compacto para o context_prompt.
    """
    if not sprint_path:
        return ""
    try:
        with open(sprint_path, "r", encoding="utf-8") as f:
            data = _yaml.safe_load(f)
        if not isinstance(data, dict):
            return f"Path da sprint: {sprint_path}"

        title = data.get("title", "sem título")
        status = data.get("status", "?")
        tasks = data.get("tasks", [])

        lines = [f'Sprint: "{title}" | Status: {status}', "Tarefas:"]
        for t in tasks:
            if not isinstance(t, dict):
                continue
            st = t.get("status", "?").upper()
            ti = t.get("title", "sem título")
            lines.append(f"  [{st}] {ti}")

        lines.append(f"Path: {sprint_path}")
        return "\n".join(lines)

    except Exception as e:
        return f"Path da sprint: {sprint_path} (erro ao ler resumo: {e})"


def _direct_route(agent_name: str, sprint_path: str, agents: dict) -> str | None:
    """
    Determina o próximo agente deterministicamente lendo o estado da sprint.
    """
    if not sprint_path:
        return None

    try:
        with open(sprint_path, "r", encoding="utf-8") as f:
            data = _yaml.safe_load(f)
        if not isinstance(data, dict):
            return None

        sprint_status = data.get("status", "open")
        tasks = data.get("tasks", []) if isinstance(data, dict) else []

        def is_blocking(t: dict) -> bool:
            return (
                isinstance(t, dict)
                and not str(t.get("title", "")).startswith("[MELHORIA]")
            )

        blocking = [t for t in tasks if is_blocking(t)]
        open_dev  = [t for t in blocking if t.get("status") == "open" and "[DEV]"  in str(t.get("title", ""))]
        open_test = [t for t in blocking if t.get("status") == "open" and "[TEST]" in str(t.get("title", ""))]
        all_done  = all(t.get("status") in ("done", "cancelled") for t in blocking)

        if sprint_status == "open" and not tasks:
            return _find_agent_by_role("arquiteto", agents)

        if open_dev:
            return _find_agent_by_role("dev", agents)

        if not open_dev and open_test:
            return _find_agent_by_role("qa", agents)

        if all_done:
            return _find_agent_by_role("janitor", agents)

        return None
    except Exception:
        return None


def _find_agent_by_role(role: str, agents: dict) -> str | None:
    role_keywords: dict[str, list[str]] = {
        "arquiteto": ["arquiteto", "architect"],
        "dev":       ["dev ", "developer", "desenvolvedor"],
        "qa":        ["qa", "quality", "teste", "tester"],
        "janitor":   ["janitor", "limpeza", "cleaner"],
    }
    keywords = role_keywords.get(role, [role])
    for agent_name in agents:
        lower = agent_name.lower()
        if any(kw in lower for kw in keywords):
            return agent_name
    return None


class Crew:
    def __init__(
        self,
        agents_list,
        client,
        mcp,
        native,
        skill_manager,
        execution_id: str | None = None,
        sprint_path: str = "",
        crew_name: str = "",
    ):
        self.agents = {a.name: a for a in agents_list}
        self.first_agent = agents_list[0] if agents_list else None
        self.client = client
        self.mcp = mcp
        self.native = native
        self.skill_manager = skill_manager
        self.router = SemanticRouter(client)
        self.sprint_path = sprint_path
        self.crew_name = crew_name
        self.execution_id = execution_id or uuid.uuid4().hex[:8]
        self.checkpoint: CheckpointManager | None = None
        self._rate_limiter = RateLimiter()

    async def run(self, task: str) -> str:
        self.checkpoint = CheckpointManager(
            execution_id=self.execution_id,
            crew_name=self.crew_name,
            sprint_path=self.sprint_path,
        )

        saved_agent = self.checkpoint.get_current_agent()
        if saved_agent and saved_agent in self.agents:
            current = self.agents[saved_agent]
            saved_history = self.checkpoint.get_agent_history(saved_agent)
            if saved_history:
                current.history = saved_history
                _log(saved_agent, f"♻️  retomada — {len(saved_history)} mensagens", current.modelId)
                context_prompt = ""
            else:
                context_prompt = self._build_initial_context(task)
        else:
            current = self.first_agent
            context_prompt = self._build_initial_context(task)

        try:
            return await self._run_loop(current, context_prompt)
        except FatalAPIError as e:
            self._handle_fatal_error(str(e))
            return f"❌ **Execução interrompida — erro fatal de API.**\n\nMotivo: {e}"

    async def _run_loop(self, current, context_prompt: str) -> str:
        while current:
            _log(current.name, "iniciando turno", current.modelId)
            tools_list = await self._prepare_tools(current)
            sys_p = current.build_system_prompt(self.skill_manager)

            result = await self._execute_loop(current, sys_p, context_prompt, tools_list)
            result_str = str(result) if result is not None else ""

            if current.clean_context:
                _log(current.name, "🧹 limpando histórico", current.modelId)
                current.history = []

            _log(current.name, "turno concluído — decidindo próximo passo", current.modelId)

            is_first_agent = current is self.first_agent
            next_name = None

            if is_first_agent and self.sprint_path:
                next_name = _direct_route(current.name, self.sprint_path, self.agents)
                if next_name:
                    _log(current.name, f"[direto] → {next_name}", current.modelId)
                else:
                    next_name = await self._semantic_route(current, result_str)
            else:
                next_name = await self._semantic_route(current, result_str)

            if next_name and next_name in self.agents:
                self.checkpoint.mark_agent_done(current.name, result_str, next_agent=next_name)
                _log(current.name, f"➔ encaminhou para {next_name}", current.modelId)
                self._mark_delegated_task_in_progress(next_name)
                context_prompt = self._build_handoff_context(current.name, result_str, next_name)
                current = self.agents[next_name]
                self.checkpoint.save(current.name, current.history, current.name)
            else:
                self.checkpoint.mark_agent_done(current.name, result_str)
                last_name = current.name
                open_tasks = self._get_open_tasks()
                if open_tasks:
                    _log(current.name, f"⚠️  {len(open_tasks)} tarefas abertas — reencaminhando", current.modelId)
                    context_prompt = (
                        f"A sprint ainda possui {len(open_tasks)} tarefas não concluídas.\n"
                        f"Retome o trabalho. Path: {self.sprint_path}\n"
                        f"Estado:\n{_sprint_summary(self.sprint_path)}"
                    )
                    current = self.first_agent
                    continue

                _log("EQUIPE", "🏁 fluxo finalizado")
                self.checkpoint.mark_done()
                return f"✅ **Trabalho concluído.**\n\n**Último resultado ({last_name}):**\n{result_str}"
        return ""

    async def _semantic_route(self, current, result_str: str) -> str | None:
        try:
            await self._rate_limiter.acquire(self.router.model_id)
            return await self.router.evaluate(current.name, result_str, current.transitions)
        except Exception as e:
            print(f"[!] Erro no roteamento: {e}")
            return None

    def _build_initial_context(self, task: str) -> str:
        parts = [f"Comando inicial: {task}"]
        if self.sprint_path:
            parts.append(f"Path da sprint: {self.sprint_path}")
            summary = _sprint_summary(self.sprint_path)
            if summary:
                parts.append(f"Estado atual:\n{summary}")
        return "\n".join(parts)

    def _build_handoff_context(self, from_agent: str, result: str, to_agent: str) -> str:
        sprint_info = f"\nPath da sprint: {self.sprint_path}" if self.sprint_path else ""
        on_demand_text = ""
        target_agent = self.agents.get(to_agent)
        if target_agent and hasattr(target_agent, 'on_demand_skills') and target_agent.on_demand_skills:
            on_demand_content = self.skill_manager.get_all_skills(selected_names=target_agent.on_demand_skills)
            if on_demand_content.strip():
                on_demand_text = f"\n\n# REFERÊNCIAS ADICIONAIS:\n{on_demand_content}"

        is_going_to_first = to_agent == (self.first_agent.name if self.first_agent else None)
        if is_going_to_first and self.sprint_path:
            summary = _sprint_summary(self.sprint_path)
            return f"Resultado de {from_agent}:\n{result}{sprint_info}\n\nEstado atual:\n{summary}{on_demand_text}"

        return f"Resultado de {from_agent}:\n{result}{sprint_info}{on_demand_text}"

    async def _execute_loop(self, agent, sys_p: str, prompt: str, tools: list) -> str:
        agent.history.append({"role": "user", "content": prompt})
        final_text = ""
        empty_input_strikes = 0

        while True:
            try:
                await self._rate_limiter.acquire(agent.modelId)
                stream_ctx = self.client.messages.stream(
                    model=agent.modelId,
                    max_tokens=_max_tokens_for(agent.modelId),
                    system=[{"type": "text", "text": sys_p, "cache_control": {"type": "ephemeral"}}],
                    messages=agent.history,
                    tools=tools if tools else None,
                )
                resp, streamed_text, tool_calls = await stream_with_thinking(stream_ctx, label=agent.name)

                if streamed_text:
                    final_text = streamed_text

                blocks = []
                for b in resp.content:
                    if b.type == "text":
                        blocks.append({"type": "text", "text": b.text})
                        if not streamed_text:
                            final_text = b.text
                            _log(agent.name, b.text, agent.modelId)
                    elif b.type == "tool_use":
                        blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})

                agent.history.append({"role": "assistant", "content": blocks})
                if self.checkpoint:
                    self.checkpoint.save(agent.name, agent.history, agent.name)

                if not tool_calls:
                    if resp.stop_reason == "max_tokens":
                        agent.history.append({"role": "user", "content": "Continue."})
                        continue
                    break

                native_tool_names = {t["name"] for t in self.native.get_tools()}
                results = []
                for tc in tool_calls:
                    tool_input = tc.input if isinstance(tc.input, dict) else {}
                    if not tool_input:
                        empty_input_strikes += 1
                        if empty_input_strikes >= 3:
                            return final_text or "[abortado] Loop de tool com input vazio."
                        results.append({"type": "tool_result", "tool_use_id": tc.id, "content": "Erro: input vazio", "is_error": True})
                        continue

                    res = (await self.native.execute_tool(tc.name, tool_input) if tc.name in native_tool_names else await self.mcp.call_tool(tc.name, tool_input))
                    empty_input_strikes = 0
                    results.append({"type": "tool_result", "tool_use_id": tc.id, "content": str(res)})

                agent.history.append({"role": "user", "content": results})
            except Exception as e:
                return f"[agent_fail] Erro técnico: {str(e)}"
        return final_text

    def _handle_fatal_error(self, reason: str) -> None:
        if self.checkpoint:
            self.checkpoint.mark_failed(reason)
        print(f"\n❌ ERRO FATAL: {reason}")

    def _mark_delegated_task_in_progress(self, next_agent_name: str) -> None:
        if not self.sprint_path:
            return
        try:
            with open(self.sprint_path, "r", encoding="utf-8") as f:
                data = _yaml.safe_load(f)
            if not isinstance(data, dict): return
            tasks = data.get("tasks", [])
            for task in tasks:
                if task.get("status") == "open":
                    task["status"] = "in_progress"
                    break
            with open(self.sprint_path, "w", encoding="utf-8") as f:
                _yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        except Exception:
            pass

    def _get_open_tasks(self) -> list[dict]:
        if not self.sprint_path: return []
        try:
            with open(self.sprint_path, "r", encoding="utf-8") as f:
                data = _yaml.safe_load(f)
            return [t for t in data.get("tasks", []) if t.get("status") not in ("done", "cancelled")]
        except Exception: return []

    async def _prepare_tools(self, agent) -> list:
        native_tools = [t for t in self.native.get_tools() if t["name"] in agent.tools]
        mcp_all = await self.mcp.get_all_tools()
        mcp_filtered = [t for t in mcp_all if any(p in t["name"] for p in agent.tools)]
        return native_tools + mcp_filtered
