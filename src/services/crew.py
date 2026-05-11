"""
crew.py
───────
Orquestra a execução sequencial de agentes em uma sprint.

Correções aplicadas (v3):
  1. Roteamento direto — bypass do roteador semântico quando o Gerente tem
     sprint_path: lê o YAML e decide o próximo agente deterministicamente,
     sem gastar uma chamada Haiku extra por turno
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
  6. Truncagem de tool results — resultados grandes (> MAX_TOOL_RESULT_TOKENS)
     são truncados antes de entrar no histórico, evitando que o messages[]
     cresça sem controle e pague preço cheio a cada turno subsequente
  7. Handoff context sumarizado — o result passado entre agentes é truncado a
     HANDOFF_MAX_CHARS para evitar que outputs grandes (ex: código Swift gerado)
     sejam reenviados inteiros no context_prompt do próximo agente
  8. Cache do messages[0] — quando o contexto inicial é estático (sprint path +
     resumo), marcamos a primeira mensagem com cache_control ephemeral para que
     a Anthropic a cacheia a partir do 2º turno do mesmo agente
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
import yaml as _yaml
from datetime import datetime
from anthropic import AuthenticationError, PermissionDeniedError, APIStatusError
from services.semantic_router import SemanticRouter
from services.checkpoint import CheckpointManager
from controllers.thinking_stream import stream_with_thinking

class FatalAPIError(Exception):
    """
    Erro não-recuperável da API (ex: 401 conta desabilitada, 403 sem permissão).
    Ao ser levantado, crew.run() para imediatamente — sem retry, sem loop.
    """
HANDOFF_MAX_CHARS = 6_000                                                
def _log(agent_name: str, action: str, model_id: str = "") -> None:
    ts = datetime.now().strftime("%H:%M")
    model_short = _short_model(model_id)
    suffix = f" - {model_short}" if model_short else ""
    print(f"[{ts}] - {agent_name} - {action}{suffix}", flush=True)

def _short_model(model_id: str) -> str:
    aliases = {
        "claude-haiku-4-5":  "Haiku",
        "claude-sonnet-4-6": "Sonnet",
        "claude-opus-4-6":   "Opus",
    }
    if not model_id:
        return ""
    for key, alias in aliases.items():
        if key in model_id:
            return alias
    return model_id.split("-")[1].capitalize() if "-" in model_id else model_id

def _sprint_summary(sprint_path: str) -> str:
    """
    Lê o YAML da sprint e devolve um resumo compacto para o context_prompt
    do Gerente — substitui a re-leitura de 95KB por tool call.

    Formato gerado (~500 chars vs ~24K tokens do YAML bruto):
        Sprint: "título" | Status: in_progress
        Tarefas:
          [DONE] [DEV] Setup do módulo Python
          [OPEN] [DEV] Serverless Framework
          [OPEN] [TEST] Testes unitários dos clients
        Path: /caminho/para/sprint.yaml
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

        lines = [f'Sprint: "{title}" | Status: {status}', "Tasks:"]
        for t in tasks:
            if not isinstance(t, dict):
                continue
            st = t.get("status", "?").upper()
            ti = t.get("title", "untitled")
            lines.append(f"  [{st}] {ti}")

        lines.append(f"Path: {sprint_path}")
        return "\n".join(lines)

    except Exception as e:
        return f"Sprint path: {sprint_path} (error reading summary: {e})"

def _direct_route(agent_name: str, sprint_path: str, agents: dict) -> str | None:
    """
    Determina o próximo agente deterministicamente lendo o estado da sprint,
    sem chamar o roteador semântico (Haiku).

    Aplicável apenas ao primeiro agente da crew (tipicamente o Gerente) quando
    sprint_path está definido. Os demais agentes (Dev, QA, Arquiteto) sempre
    usam o roteador semântico — sua saída textual é necessária para a decisão.

    Retorna:
        str  — nome do próximo agente (deve existir em `agents`)
        None — não foi possível determinar; usar roteador semântico normalmente
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
            title = str(t.get("title", "")).strip()
            return (
                isinstance(t, dict)
                and bool(title)                          # ignora tarefas sem título
                and not title.startswith("[MELHORIA]")
            )

        def is_improvement(t: dict) -> bool:
            title = str(t.get("title", "")).strip()
            return isinstance(t, dict) and title.startswith("[MELHORIA]") and bool(title)

        blocking     = [t for t in tasks if is_blocking(t)]
        improvements = [t for t in tasks if is_improvement(t)]

        # Tarefas open ou in_progress são consideradas "pendentes" para roteamento.
        # in_progress pode ter ficado orphaned após interrupção — deve ser retomada.
        open_or_wip_dev  = [
            t for t in blocking
            if t.get("status") in ("open", "in_progress") and "[DEV]" in str(t.get("title", ""))
        ]
        open_or_wip_test = [
            t for t in blocking
            if t.get("status") in ("open", "in_progress") and "[TEST]" in str(t.get("title", ""))
        ]
        all_blocking_done = all(t.get("status") in ("done", "cancelled") for t in blocking) if blocking else True

        # Melhorias open/in_progress — só são processadas quando todas as tarefas
        # bloqueantes já estão concluídas (done/cancelled).
        open_improvements = [
            t for t in improvements
            if t.get("status") in ("open", "in_progress")
        ]

        if sprint_status == "open" and not tasks:
            target = _find_agent_by_role("arquiteto", agents)
            return target

        if open_or_wip_dev:
            target = _find_agent_by_role("dev", agents)
            if target:
                return target

        if not open_or_wip_dev and open_or_wip_test:
            target = _find_agent_by_role("qa", agents)
            if target:
                return target

        # Todas as tarefas bloqueantes concluídas — verifica melhorias pendentes.
        # Melhorias [MELHORIA] seguem o mesmo roteamento por prefixo:
        #   [MELHORIA][DEV] → dev   |   [MELHORIA][TEST] → qa   |   outros → dev (fallback)
        if all_blocking_done and open_improvements:
            impr_dev  = [t for t in open_improvements if "[DEV]"  in str(t.get("title", ""))]
            impr_test = [t for t in open_improvements if "[TEST]" in str(t.get("title", ""))]

            if impr_dev:
                target = _find_agent_by_role("dev", agents)
                if target:
                    _log(agent_name, f"🔧 {len(open_improvements)} melhoria(s) pendente(s) — roteando para {target}")
                    return target

            if not impr_dev and impr_test:
                target = _find_agent_by_role("qa", agents)
                if target:
                    _log(agent_name, f"🔧 {len(open_improvements)} melhoria(s) pendente(s) — roteando para {target}")
                    return target

            # Melhorias sem prefixo específico → dev como fallback
            target = _find_agent_by_role("dev", agents)
            if target:
                _log(agent_name, f"🔧 {len(open_improvements)} melhoria(s) pendente(s) — roteando para {target} (fallback)")
                return target

        if all_blocking_done and not open_improvements:
            target = _find_agent_by_role("janitor", agents)
            return target
        return None

    except Exception:
        return None

def _find_agent_by_role(role: str, agents: dict) -> str | None:
    """
    Heurística de correspondência de nome de agente por papel.
    Procura pelo role como substring case-insensitive no nome do agente.
    """
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

def _is_architect(agent_name: str) -> bool:
    """Retorna True se o agente é um Arquiteto/Architect."""
    lower = agent_name.lower()
    return "arquiteto" in lower or "architect" in lower

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
                _log(saved_agent, f"♻️  retomada — {len(saved_history)} mensagens no histórico", current.modelId)
                if self.sprint_path:
                    summary = _sprint_summary(self.sprint_path)
                    context_prompt = (
                        f"Resuming interrupted execution. Current sprint state:\n{summary}\n\n"
                        "Continue from where you left off. Do not create new tasks — resume "
                        "existing tasks with status 'in_progress' or 'open'."
                    )
                else:
                    context_prompt = (
                        "Resuming interrupted execution. Continue from where you left off. "
                        "Do not create new tasks — resume existing tasks."
                    )
            else:
                # Histórico vazio: agente foi salvo no checkpoint mas sem mensagens.
                # Reconstruir o context_prompt de retomada sem histórico para evitar
                # que o agente crie tarefas em branco ao receber o sprint_path bruto.
                _log(saved_agent, "♻️  retomada sem histórico — reconstruindo contexto", current.modelId)
                if self.sprint_path:
                    summary = _sprint_summary(self.sprint_path)
                    context_prompt = (
                        f"Resuming interrupted execution (no saved history).\n"
                        f"Current sprint state:\n{summary}\n\n"
                        "Read the sprint file to check each task's status. "
                        "Resume tasks with status 'in_progress' or 'open'. "
                        "Do not create new tasks."
                    )
                else:
                    context_prompt = self._build_initial_context(task)
        else:
            current = self.first_agent
            context_prompt = self._build_initial_context(task)

        # Lê o status atual da sprint para decidir o que resetar antes de iniciar.
        _sprint_current_status = "open"
        if self.sprint_path:
            try:
                with open(self.sprint_path, "r", encoding="utf-8") as _f:
                    _d = _yaml.safe_load(_f)
                _sprint_current_status = (_d or {}).get("status", "open")
            except Exception:
                pass

        # Re-execução de sprint done (para processar melhorias pendentes):
        # reseta melhorias in_progress orphaned para 'open' antes de começar.
        if _sprint_current_status == "done":
            reset_n = self._reset_orphaned_in_progress_tasks(include_improvements=True)
            if reset_n:
                _log("crew", f"🔄 re-execução: {reset_n} melhoria(s) orphaned regredidas para open")

        # Retomada de execução interrompida: reseta tarefas bloqueantes in_progress.
        elif saved_agent and saved_agent in self.agents:
            reset_n = self._reset_orphaned_in_progress_tasks()
            if reset_n:
                _log("crew", f"♻️  retomada: {reset_n} tarefa(s) orphaned regredidas para open")

        self._mark_sprint_in_progress()

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
                _log(current.name, "🧹 limpando histórico de contexto", current.modelId)
                current.history = []

            _log(current.name, "turno concluído — decidindo próximo passo", current.modelId)

            is_first_agent = current is self.first_agent
            next_name: str | None = None

            if is_first_agent and self.sprint_path:
                next_name = _direct_route(current.name, self.sprint_path, self.agents)
                if next_name:
                    _log(current.name, f"[direto] → {next_name} (roteador semântico ignorado)", current.modelId)
                else:
                    next_name = await self._semantic_route(current, result_str)
            else:
                next_name = await self._semantic_route(current, result_str)

            if next_name and next_name in self.agents:
                self.checkpoint.mark_agent_done(current.name, result_str, next_agent=next_name)
                _log(current.name, f"➔ encaminhou para {next_name}", current.modelId)

                delegated_title = self._mark_delegated_task_in_progress(next_name)
                if delegated_title:
                    _log(next_name, f"📋 tarefa marcada in_progress: {delegated_title}")

                context_prompt = self._build_handoff_context(current.name, result_str, next_name)

                current = self.agents[next_name]
                self.checkpoint.save(current.name, current.history, current.name)

            else:
                self.checkpoint.mark_agent_done(current.name, result_str)
                last_name = current.name

                open_tasks = self._get_open_tasks()
                if open_tasks:
                    _log(current.name, f"⚠️  fluxo encerrou com {len(open_tasks)} tarefa(s) em aberto — reencaminhando ao primeiro agente", current.modelId)
                    task_lines = "\n".join(
                        f"  - [{t.get('status','?').upper()}] {t.get('title','sem título')}"
                        for t in open_tasks
                    )
                    context_prompt = (
                        f"Flow ended but sprint still has {len(open_tasks)} incomplete task(s):\n\n"
                        f"{task_lines}\n\n"
                        f"Resume work from these tasks.\n"
                        f"Sprint path: {self.sprint_path}\n\n"
                        f"Current state:\n{_sprint_summary(self.sprint_path)}"
                    )
                    current = self.first_agent
                    _log(current.name, f"➔ reencaminhando para {current.name}", current.modelId)
                    continue

                _log("EQUIPE", "🏁 fluxo finalizado")
                current = None
                self.checkpoint.mark_done()
                return (
                    f"✅ **A equipe terminou o trabalho.**\n\n"
                    f"**Último resultado ({last_name}):**\n{result_str}"
                )

        return ""

    async def _semantic_route(self, current, result_str: str) -> str | None:
        """Chama o roteador semântico."""
        try:
            return await self.router.evaluate(current.name, result_str, current.transitions)
        except (AuthenticationError, PermissionDeniedError) as e:
            raise FatalAPIError(str(e)) from e
        except APIStatusError as e:
            if e.status_code in (401, 403):
                raise FatalAPIError(str(e)) from e
            raise

    def _build_initial_context(self, task: str) -> str:
        parts = [f"Task: {task}"]
        if self.sprint_path:
            parts.append(f"\nSprint path: {self.sprint_path}")
            summary = _sprint_summary(self.sprint_path)
            if summary:
                parts.append(f"\nCurrent sprint state:\n{summary}")
        return "\n".join(parts)

    def _build_handoff_context(self, from_agent: str, result: str, to_agent: str) -> str:
        """
        Constrói o context_prompt para a transição entre agentes.

        Correção 3: se o agente de destino tem `on_demand_skills`, injeta o
        conteúdo dessas skills no context_prompt (não no system prompt fixo).
        Isso evita que skills pesadas (ex: META-github-repos-map, ~18K tokens)
        sejam reenviadas em todas as chamadas API do agente.

        Correção 4: o path da sprint viaja explicitamente em todas as transições.

        Correção 5: para o Gerente (first_agent), injeta resumo compacto da sprint
        em vez de deixá-lo re-ler 95KB via tool call a cada turno.

        Correção 7: o result é truncado a HANDOFF_MAX_CHARS antes de ser incluído.
        Outputs grandes (ex: código Swift gerado pelo Dev) não precisam ser
        reenviados inteiros ao próximo agente — o resumo executivo é suficiente.
        """
        result_truncated = result
        if len(result) > HANDOFF_MAX_CHARS:
            result_truncated = (
                result[:HANDOFF_MAX_CHARS]
                + f"\n\n[... resultado truncado — {len(result)} chars originais, exibindo primeiros {HANDOFF_MAX_CHARS} ...]"
            )
            _log(from_agent, f"✂️  handoff result truncado: {len(result)} → {HANDOFF_MAX_CHARS} chars")

        sprint_info = ""
        if self.sprint_path:
            sprint_info = f"\nSprint path: {self.sprint_path}"

        on_demand_text = ""
        target_agent = self.agents.get(to_agent)
        if target_agent and target_agent.on_demand_skills:
            on_demand_content = self.skill_manager.get_all_skills(
                selected_names=target_agent.on_demand_skills
            )
            if on_demand_content.strip():
                on_demand_text = f"\n\n# REFERÊNCIAS ADICIONAIS PARA ESTE TURNO:\n{on_demand_content}"

        is_going_to_first = to_agent == self.first_agent.name if self.first_agent else False
        if is_going_to_first and self.sprint_path:
            summary = _sprint_summary(self.sprint_path)
            return (
                f"Result from {from_agent}:\n{result_truncated}"
                f"{sprint_info}\n\n"
                f"Current sprint state:\n{summary}"
                f"{on_demand_text}"
            )

        return f"Result from {from_agent}:\n{result_truncated}{sprint_info}{on_demand_text}"

    async def _execute_loop(self, agent, sys_p: str, prompt: str, tools: list) -> str:
        first_msg: dict
        if not agent.history:
            first_msg = {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        else:
            first_msg = {"role": "user", "content": prompt}

        if prompt:
            agent.history.append(first_msg)
        final_text = ""
        empty_input_strikes = 0
        MAX_EMPTY_INPUT_STRIKES = 3
        native_tool_names = {t["name"] for t in self.native.get_tools()}

        while True:
            try:
                stream_ctx = self.client.messages.stream(
                    model=agent.modelId,
                    max_tokens=32_000,
                    system=[{"type": "text", "text": sys_p, "cache_control": {"type": "ephemeral"}}],
                    messages=agent.history,
                    tools=tools if tools else None,
                )
                resp, streamed_text, tool_calls = await stream_with_thinking(
                    stream_ctx, label=agent.name
                )

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

                results = []
                for tc in tool_calls:
                    tool_input = tc.input if isinstance(tc.input, dict) else {}

                    if not tool_input:
                        empty_input_strikes += 1
                        _log(agent.name, f"⚠️  {tc.name} input VAZIO — strike {empty_input_strikes}/{MAX_EMPTY_INPUT_STRIKES}", agent.modelId)
                        if empty_input_strikes >= MAX_EMPTY_INPUT_STRIKES:
                            _log(agent.name, f"🛑 {MAX_EMPTY_INPUT_STRIKES} inputs vazios — abortando loop", agent.modelId)
                            return final_text or "[aborted] Model in tool loop with empty input."
                        results.append({
                            "type": "tool_result",
                            "tool_use_id": tc.id,
                            "content": (
                                f"❌ {tc.name} blocked: empty input {{}}.\n"
                                "   Resend with required parameters filled in.\n"
                                f"   ⚠️  Strike {empty_input_strikes}/{MAX_EMPTY_INPUT_STRIKES}"
                            ),
                            "is_error": True,
                        })
                        continue

                    input_str = str(tool_input).replace("\n", " ")
                    display_input = (input_str[:97] + "...") if len(input_str) > 100 else input_str
                    _log(agent.name, f"🔧 {tc.name} [{display_input}]", agent.modelId)

                    res = (
                        await self.native.execute_tool(tc.name, tool_input)
                        if tc.name in native_tool_names
                        else await self.mcp.call_tool(tc.name, tool_input)
                    )
                    empty_input_strikes = 0

                    res_str = str(res)
                    results.append({"type": "tool_result", "tool_use_id": tc.id, "content": res_str})

                agent.history.append({"role": "user", "content": results})

            except (AuthenticationError, PermissionDeniedError) as e:
                raise FatalAPIError(str(e)) from e
            except APIStatusError as e:
                if e.status_code in (401, 403):
                    raise FatalAPIError(str(e)) from e
                return f"[agent_fail] Erro técnico no processamento: {str(e)}"
            except FatalAPIError:
                raise
            except Exception as e:
                return f"[agent_fail] Erro técnico no processamento: {str(e)}"

        return final_text

    def _handle_fatal_error(self, reason: str) -> None:
        """
        Para por erro fatal não-recuperável (401/403).
        Marca checkpoint como failed, registra update na sprint e printa no console.
        """
        ts = datetime.now().strftime("%H:%M")

        if self.checkpoint:
            self.checkpoint.mark_failed(reason)

        if self.sprint_path:
            try:
                with open(self.sprint_path, "r", encoding="utf-8") as f:
                    data = _yaml.safe_load(f) or {}

                updates = data.get("updates", [])
                if not isinstance(updates, list):
                    updates = []
                updates.append(f"[{ts}] ❌ EXECUÇÃO INTERROMPIDA — erro fatal de API: {reason}")
                data["updates"] = updates

                tmp_fd, tmp_path = tempfile.mkstemp(
                    dir=os.path.dirname(self.sprint_path), suffix=".tmp"
                )
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    _yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
                os.replace(tmp_path, self.sprint_path)

            except Exception as write_err:
                print(f"[!] Não foi possível registrar o erro na sprint: {write_err}", flush=True)

        sep = "=" * 60
        print(f"\n{sep}", flush=True)
        print(f"  ❌  EXECUÇÃO INTERROMPIDA — ERRO FATAL DE API", flush=True)
        print(sep, flush=True)
        print(f"  Horário : {ts}", flush=True)
        print(f"  Motivo  : {reason}", flush=True)
        print(f"  Ação    : Verifique as credenciais da API (limite de conta,", flush=True)
        print(f"            conta desabilitada ou chave inválida) e reinicie.", flush=True)
        print(f"{sep}\n", flush=True)

    def _reset_orphaned_in_progress_tasks(self, include_improvements: bool = False) -> int:
        """
        Ao retomar uma execução interrompida (ou ao re-executar uma sprint done),
        tarefas com status 'in_progress' podem ter ficado sem agente ativo (orphaned).

        Esta função as regride para 'open' para que o roteamento as pegue
        normalmente no próximo ciclo — evitando que a sprint fique travada.

        Args:
            include_improvements: Se True, inclui tarefas [MELHORIA] no reset.
                                   Use ao re-executar uma sprint done para processar
                                   melhorias pendentes que ficaram in_progress.

        Retorna o número de tarefas resetadas.
        """
        if not self.sprint_path:
            return 0
        try:
            with open(self.sprint_path, "r", encoding="utf-8") as f:
                data = _yaml.safe_load(f)
            if not isinstance(data, dict):
                return 0

            tasks = data.get("tasks", [])
            ts = datetime.now().strftime("%H:%M")
            reset_count = 0

            for task in tasks:
                if not isinstance(task, dict):
                    continue
                title = str(task.get("title", "")).strip()
                if not title:
                    continue

                is_improvement = title.startswith("[MELHORIA]")

                # Por padrão, não reseta melhorias (comportamento de retomada normal).
                # Com include_improvements=True (re-execução de sprint done), reseta tudo.
                if is_improvement and not include_improvements:
                    continue

                if task.get("status") != "in_progress":
                    continue

                task["status"] = "open"
                updates = task.get("updates")
                if not isinstance(updates, list):
                    updates = []
                reason = (
                    "re-execução de sprint — processando melhorias pendentes"
                    if is_improvement
                    else "tarefa orphaned por interrupção — retomando"
                )
                updates.append(
                    f"[{ts}] status regredido de in_progress → open ({reason})"
                )
                task["updates"] = updates
                reset_count += 1

            if reset_count == 0:
                return 0

            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=os.path.dirname(self.sprint_path), suffix=".tmp"
            )
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                _yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            os.replace(tmp_path, self.sprint_path)

            _log("crew", f"🔄 {reset_count} tarefa(s) in_progress regredidas para open")
            return reset_count

        except Exception as e:
            _log("crew", f"[!] _reset_orphaned_in_progress_tasks: {e}")
            return 0

    def _mark_sprint_in_progress(self) -> None:
        """
        Muda o status da sprint para 'in_progress' ao iniciar execução.

        Aceita sprint nos estados 'open', 'done' e 'in_progress' (retomada):
          - 'open'        → in_progress (início normal)
          - 'done'        → in_progress (re-execução para processar melhorias)
          - 'in_progress' → mantém (retomada de execução interrompida)
        """
        if not self.sprint_path:
            return
        try:
            with open(self.sprint_path, "r", encoding="utf-8") as f:
                data = _yaml.safe_load(f)
            if not isinstance(data, dict):
                return

            current_status = data.get("status", "open")

            # Só altera se o status for 'open' ou 'done' (re-execução com melhorias)
            if current_status not in ("open", "done"):
                return

            ts = datetime.now().strftime("%H:%M")
            updates = data.get("updates")
            if not isinstance(updates, list):
                updates = []

            if current_status == "done":
                # Re-execução: sprint foi concluída mas há melhorias pendentes.
                # Reabre a sprint para processar as melhorias.
                data["status"] = "in_progress"
                updates.append(
                    f"[{ts}] sprint reaberta para processar melhorias pendentes "
                    f"(status: done → in_progress)"
                )
                _log("crew", f"🔄 sprint reaberta para melhorias: {self.sprint_path}")
            else:
                data["status"] = "in_progress"
                updates.append(f"[{ts}] status alterado para in_progress — execução iniciada")
                _log("crew", f"📋 sprint marcada in_progress: {self.sprint_path}")

            data["updates"] = updates

            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=os.path.dirname(self.sprint_path), suffix=".tmp"
            )
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                _yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            os.replace(tmp_path, self.sprint_path)
        except Exception as e:
            _log("crew", f"[!] _mark_sprint_in_progress: {e}")

    def _mark_delegated_task_in_progress(self, next_agent_name: str) -> str | None:
        """
        Marca a primeira tarefa open da sprint como in_progress no YAML,
        imediatamente antes de o agente executor receber o turno.

        Só atualiza tarefas cujo prefixo de tipo corresponde ao papel do agente:
          - "dev"  → tarefas [DEV]
          - "qa"   → tarefas [TEST]
          - outros → qualquer tarefa open (Arquiteto, Janitor, etc.)

        Usa escrita atômica (tempfile + replace) para não corromper o arquivo.
        Retorna o título da tarefa marcada, ou None se nenhuma foi encontrada.
        """
        if not self.sprint_path:
            return None

        lower_name = next_agent_name.lower()
        if any(kw in lower_name for kw in ["dev ", "developer", "desenvolvedor"]):
            expected_prefix = "[DEV]"
        elif any(kw in lower_name for kw in ["qa", "quality", "tester"]):
            expected_prefix = "[TEST]"
        else:
            expected_prefix = None                              
        try:
            with open(self.sprint_path, "r", encoding="utf-8") as f:
                data = _yaml.safe_load(f)
            if not isinstance(data, dict):
                return None

            tasks = data.get("tasks", [])
            marked_title: str | None = None
            ts = datetime.now().strftime("%H:%M")

            # Verifica se todas as tarefas bloqueantes já estão concluídas,
            # para decidir se melhorias podem ser delegadas neste ciclo.
            blocking_tasks = [
                t for t in tasks
                if isinstance(t, dict)
                and str(t.get("title", "")).strip()
                and not str(t.get("title", "")).strip().startswith("[MELHORIA]")
            ]
            all_blocking_done = all(
                t.get("status") in ("done", "cancelled") for t in blocking_tasks
            ) if blocking_tasks else True

            for task in tasks:
                if not isinstance(task, dict):
                    continue
                title = str(task.get("title", "")).strip()
                status = task.get("status", "")

                if not title:                               # ignora tarefas sem título
                    continue
                if status != "open":
                    continue

                is_improvement = title.startswith("[MELHORIA]")

                # Melhorias só são delegadas quando todas as bloqueantes estão done
                if is_improvement and not all_blocking_done:
                    continue

                if expected_prefix and expected_prefix not in title:
                    continue

                task["status"] = "in_progress"
                updates = task.get("updates")
                if not isinstance(updates, list):
                    updates = []
                updates.append(f"[{ts}] status alterado para in_progress — delegada ao agente {next_agent_name}")
                task["updates"] = updates
                marked_title = title
                break

            if not marked_title:
                return None

            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=os.path.dirname(self.sprint_path), suffix=".tmp"
            )
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                _yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            os.replace(tmp_path, self.sprint_path)

            return marked_title

        except Exception as e:
            _log("crew", f"[!] _mark_delegated_task_in_progress: {e}")
            return None

    def _get_open_tasks(self) -> list[dict]:
        """
        Lê a sprint e retorna tarefas que não estão done/cancelled.

        Inclui tarefas 'in_progress' — elas podem ter ficado orphaned após uma
        interrupção e precisam ser retomadas da mesma forma que tarefas 'open'.
        """
        if not self.sprint_path:
            return []
        try:
            with open(self.sprint_path, "r", encoding="utf-8") as f:
                data = _yaml.safe_load(f)
            tasks = data.get("tasks", []) if isinstance(data, dict) else []
            return [
                t for t in tasks
                if isinstance(t, dict)
                and t.get("status") not in ("done", "cancelled")
                and str(t.get("title", "")).strip()          # ignora tarefas sem título
                and not str(t.get("title", "")).startswith("[MELHORIA]")
            ]
        except Exception as e:
            print(f"[!] _get_open_tasks: não foi possível ler a sprint '{self.sprint_path}': {e}")
            return []

    async def _prepare_tools(self, agent) -> list:
        native_tools = [t for t in self.native.get_tools() if t["name"] in agent.tools]
        mcp_all = await self.mcp.get_all_tools()
        mcp_filtered = [t for t in mcp_all if any(p in t["name"] for p in agent.tools)]
        
        all_tools = native_tools + mcp_filtered
        
        # Remove 'default' field from all properties in the schema for Gemini compatibility
        for tool in all_tools:
            if "input_schema" in tool and "properties" in tool["input_schema"]:
                for prop_name, prop_details in tool["input_schema"]["properties"].items():
                    if "default" in prop_details:
                        del prop_details["default"]
                        
        return all_tools
