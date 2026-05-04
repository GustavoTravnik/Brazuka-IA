import os

BLUE_BOLD, RESET = "\033[1;34m", "\033[0m"

DEFAULT_SKILLS = []


class SkillManager:
    def __init__(self, skills_path: str | None = None) -> None:
        if skills_path is None:
            base_dir    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            skills_path = os.path.join(base_dir, "skills")
        self.skills_path = skills_path

    def get_all_skills(self, selected_names: list[str] | None = None) -> str:
        effective = list(selected_names) if selected_names else []
        for s in DEFAULT_SKILLS:
            if s not in effective:
                effective.append(s)

        if not os.path.exists(self.skills_path):
            return "[AVISO] Diretório de skills não encontrado."

        files = [f for f in os.listdir(self.skills_path) if f.endswith(".md")]
        if not files:
            return "[AVISO] Nenhum arquivo .md encontrado em skills/."

        parts: list[str] = ["\n\n=== EXPERT SKILLS LOADED ===\n"]
        loaded: list[str] = []

        for filename in sorted(files):
            skill_name = filename[:-3]
            if skill_name not in effective:
                continue
            try:
                file_path = os.path.join(self.skills_path, filename)
                with open(file_path, "r", encoding="utf-8") as f:
                    parts.append(f"\n----- \nSKILL [{filename}]:\n{f.read()}\n")
                loaded.append(f"    > {skill_name}")
            except OSError as e:
                parts.append(f"\n[ERRO ao carregar '{filename}']: {e}\n")

        if not loaded:
            return "\n[AVISO] Nenhuma das skills especificadas foi encontrada."

        loaded_list = "\n".join(loaded)
        print(f"{BLUE_BOLD}========= {len(loaded)} Skill(s) Carregada(s) =========\n{loaded_list}\n=====================================\n{RESET}")

        return "".join(parts)
