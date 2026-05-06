class Agent:
    def __init__(self, data):
        self.name = data.get('name')
        self.modelId = data.get('modelId')
        self.skills = data.get('skills', [])
        self.on_demand_skills: list[str] = data.get('on_demand_skills', [])
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
            f"# {self.name}\n"
            f"{self.persona}\n\n"
            f"# ROLES:\n{roles_text}\n\n"
            f"# SKILLS:\n{skills_text}\n\n"
            f"# OUTPUT:\n{self.output_flow}\n\n"
            "If you fail or the task is impossible, start your response with \"[agent_fail]\".\n"
        )
