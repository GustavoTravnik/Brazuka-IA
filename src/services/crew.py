import asyncio
import uuid
import yaml as _yaml
from datetime import datetime
from services.semantic_router import SemanticRouter
from services.checkpoint import CheckpointManager


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

class Crew:
    def __init__(self, agents_list, client, mcp, native, skill_manager,
                 execution_id: str | None = None, sprint_path: str = "", crew_name: str = ""):
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

    async def run(self, task):
        # ── Inicializa checkpoint ────────────────────────────────────────────
        self.checkpoint = CheckpointManager(
            execution_id=self.execution_id,
            crew_name=self.crew_name,
            sprint_path=self.sprint_path,
        )

        # ── Detecta retomada: se há checkpoint anterior com agente salvo ────
        saved_agent = self.checkpoint.get_current_agent()
        if saved_agent and saved_agent in self.agents:
            current = self.agents[saved_agent]
            # Restaura o history salvo do agente interrompido
            saved_history = self.checkpoint.get_agent_history(saved_agent)
            if saved_history:
                current.history = saved_history
                _log(saved_agent, f"♻️  retomada — {len(saved_history)} mensagens no histórico", current.modelId)
                context_prompt = ""  # histórico já está carregado, não precisa reinjetar
            else:
                context_prompt = f"Comando inicial: {task}"
        else:
            current = self.first_agent
            context_prompt = f"Comando inicial: {task}"

        while current:
            _log(current.name, "iniciando turno", current.modelId)

            tools_list = await self._prepare_tools(current)
            sys_p = current.build_system_prompt(self.skill_manager)

            result = await self._execute_loop(current, sys_p, context_prompt, tools_list)
            result_str = str(result) if result is not None else ""

            if current.clean_context:
                _log(current.name, "🧹 limpando histórico de contexto", current.modelId)
                current.history = []

            _log(current.name, "turno concluído — roteador decidindo próximo passo", current.modelId)
            next_name = await self.router.evaluate(current.name, result_str, current.transitions)

            if next_name and next_name in self.agents:
                # Atualiza checkpoint com next_agent ANTES de entrar no loop do próximo
                # — garante que um crash entre agentes retome pelo agente certo
                self.checkpoint.mark_agent_done(current.name, result_str, next_agent=next_name)
                _log(current.name, f"➔ encaminhou para {next_name}", current.modelId)
                context_prompt = f"Resultado anterior de {current.name}:\n{result_str}"
                current = self.agents[next_name]
                self.checkpoint.save(current.name, current.history, current.name)
            else:
                self.checkpoint.mark_agent_done(current.name, result_str)
                last_name = current.name

                # ── Valida se a sprint está realmente concluída ──────────────
                open_tasks = self._get_open_tasks()
                if open_tasks:
                    _log(current.name, f"⚠️  fluxo encerrou com {len(open_tasks)} tarefa(s) em aberto — reencaminhando ao primeiro agente", current.modelId)
                    task_lines = "\n".join(
                        f"  - [{t.get('status','?').upper()}] {t.get('title','sem título')}"
                        for t in open_tasks
                    )
                    context_prompt = (
                        f"O fluxo da equipe chegou ao fim mas a sprint ainda possui "
                        f"{len(open_tasks)} tarefa(s) não concluída(s):\n\n"
                        f"{task_lines}\n\n"
                        f"Retome o trabalho a partir dessas tarefas. "
                        f"O path da sprint é: {self.sprint_path}"
                    )
                    current = self.first_agent
                    _log(current.name, f"➔ reencaminhando para {current.name}", current.modelId)
                    continue

                # ── Tudo done: encerra de verdade ────────────────────────────
                _log("EQUIPE", "🏁 fluxo finalizado")
                current = None
                self.checkpoint.mark_done()
                return f"✅ **A equipe terminou o trabalho.**\n\n**Último resultado ({last_name}):**\n{result_str}"

    def _get_open_tasks(self) -> list[dict]:
        """Lê o arquivo de sprint e retorna tarefas que NÃO estão com status done/cancelled."""
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
                and not str(t.get("title", "")).startswith("[MELHORIA]")
            ]
        except Exception as e:
            print(f"[!] _get_open_tasks: não foi possível ler a sprint '{self.sprint_path}': {e}")
            return []

    async def _prepare_tools(self, agent):
        native_tools = [t for t in self.native.get_tools() if t["name"] in agent.tools]
        mcp_all = await self.mcp.get_all_tools()
        mcp_filtered = [t for t in mcp_all if any(p in t["name"] for p in agent.tools)]
        return native_tools + mcp_filtered

    async def _execute_loop(self, agent, sys_p, prompt, tools):
        agent.history.append({"role": "user", "content": prompt})
        final_text = ""
        empty_input_strikes = 0
        MAX_EMPTY_INPUT_STRIKES = 3

        while True:
            try:
                async with self.client.messages.stream(
                    model=agent.modelId,
                    max_tokens=16000,
                    system=[{"type": "text", "text": sys_p, "cache_control": {"type": "ephemeral"}}],
                    messages=agent.history,
                    tools=tools if tools else None,
                ) as stream:
                    resp = await stream.get_final_message()
                
                blocks, tool_calls = [], []
                for b in resp.content:
                    if b.type == "text":
                        blocks.append({"type": "text", "text": b.text})
                        final_text = b.text
                        _log(agent.name, b.text, agent.modelId)
                    elif b.type == "tool_use":
                        blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                        tool_calls.append(b)

                agent.history.append({"role": "assistant", "content": blocks})

                # Persiste o history após cada resposta do modelo
                if self.checkpoint:
                    self.checkpoint.save(agent.name, agent.history, agent.name)

                # Se o modelo parou por limite de tokens sem tool_calls, pede continuação
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
                        _log(agent.name, f"⚠️  {tc.name} input VAZIO — strike {empty_input_strikes}/{MAX_EMPTY_INPUT_STRIKES}", agent.modelId)
                        if empty_input_strikes >= MAX_EMPTY_INPUT_STRIKES:
                            _log(agent.name, f"🛑 {MAX_EMPTY_INPUT_STRIKES} inputs vazios consecutivos — abortando loop para evitar loop infinito", agent.modelId)
                            return final_text or "[abortado] Modelo ficou em loop de tool com input vazio."
                        results.append({
                            "type": "tool_result",
                            "tool_use_id": tc.id,
                            "content": (
                                f"❌ {tc.name} bloqueado: input chegou vazio {{}}.\n"
                                "   Reenvie a chamada com os parâmetros obrigatórios preenchidos.\n"
                                f"   ⚠️  Strike {empty_input_strikes}/{MAX_EMPTY_INPUT_STRIKES} — após {MAX_EMPTY_INPUT_STRIKES} erros consecutivos o loop será abortado."
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
                    empty_input_strikes = 0  # tool executou com sucesso — reseta o contador
                    results.append({"type": "tool_result", "tool_use_id": tc.id, "content": str(res)})
                
                agent.history.append({"role": "user", "content": results})
            except Exception as e:
                return f"[agent_fail] Erro técnico no processamento: {str(e)}"
        
        return final_text
