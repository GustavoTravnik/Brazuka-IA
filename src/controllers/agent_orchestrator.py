import os
import sys
import uuid
import yaml
from models.agent import Agent
from services.crew import Crew
from services.checkpoint import CheckpointManager


class Orquestrador:
    def __init__(self, path, client, mcp, native, skill_manager,
                 execution_id: str | None = None, sprint_path: str = ""):
        self.client = client
        self.mcp = mcp
        self.native = native
        self.skill_manager = skill_manager
        self.crew_path = path
        self.sprint_path = sprint_path
        self.crew_name = os.path.splitext(os.path.basename(path))[0]
        self.execution_id = execution_id or uuid.uuid4().hex[:8]
        self.crew = self._load_crew(path)

    def _load_crew(self, path: str) -> Crew:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Arquivo de configuração não encontrado: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        existing = CheckpointManager.find_resumable(self.crew_name, self.sprint_path)
        if existing:
            self.execution_id = existing["execution_id"]
            print(f"\n[♻️ ] Checkpoint encontrado para '{self.crew_name}' — execution_id: {self.execution_id}")
            print(f"     Último agente ativo: {existing.get('current_agent')} | Atualizado: {existing.get('updated_at')}")
            if sys.stdin.isatty():
                answer = input("     Deseja retomar de onde parou? (Y/n): ").strip().lower()
                if answer == "n":
                    self.execution_id = uuid.uuid4().hex[:8]
                    print(f"     Nova execução iniciada: {self.execution_id}")
            else:
                print("     [auto] Modo não-interativo — retomando automaticamente.")

        agent_objects = [Agent(a_data) for a_data in data.get("crew", [])]
        print(f"\n[✅] Equipe '{os.path.basename(path)}' carregada com sucesso!")

        return Crew(
            agent_objects, self.client, self.mcp, self.native, self.skill_manager,
            execution_id=self.execution_id,
            sprint_path=self.sprint_path,
            crew_name=self.crew_name,
        )

    async def run(self, task):
        return await self.crew.run(task)
