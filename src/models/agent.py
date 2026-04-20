class Agent:
    def __init__(self, data):
        self.name = data.get('name')
        self.modelId = data.get('modelId')
        self.skills = data.get('skills', [])
        self.persona = data.get('persona', "")
        self.roles = data.get('roles', [])
        self.tools = data.get('tools', [])
        self.output_flow = data.get('output_flow', "")
        self.transitions = data.get('transitions', [])
        self.clean_context = data.get('clean_context_after_run', False)
        self.history = []

    def build_system_prompt(self, skill_manager) -> str:
        roles_text = "\n".join(f"- {r}" for r in self.roles)
        skills_text = skill_manager.get_all_skills(selected_names=self.skills)
        return (
            f"# IDENTIDADE: {self.name}\n"
            f"{self.persona}\n\n"
            f"# SUAS FUNÇÕES E OBJETIVOS:\n{roles_text}\n\n"
            f"# SKILLS TÉCNICAS DISPONÍVEIS:\n{skills_text}\n\n"
            f"# FORMATO DE SAÍDA ESPERADO:\n{self.output_flow}\n\n"
            "IMPORTANTE: Se você falhar ou a tarefa for impossível de realizar, "
            "comece a resposta obrigatoriamente com \"[agent_fail]\".\n"
        )
