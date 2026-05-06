import os

BLUE_BOLD, RESET = "\033[1;34m", "\033[0m"

class SkillManager:
    def __init__(self, skills_path: str | None = None) -> None:
        if skills_path is None:
            base_dir    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            skills_path = os.path.join(base_dir, "skills")
        self.skills_path = skills_path

    def get_all_skills(self, selected_names: list[str] | None = None) -> str:
        effective = list(selected_names) if selected_names else []

        if not os.path.exists(self.skills_path):
            return "[WARNING] Skills directory not found."

        files = [f for f in os.listdir(self.skills_path) if f.endswith(".md")]
        if not files:
            return "[WARNING] No .md files found in skills/."

        parts: list[str] = []
        loaded: list[str] = []

        for filename in sorted(files):
            skill_name = filename[:-3]
            if skill_name not in effective:
                continue
            try:
                file_path = os.path.join(self.skills_path, filename)
                with open(file_path, "r", encoding="utf-8") as f:
                    parts.append(f"\n---\nSKILL [{filename}]:\n{f.read()}\n")
                loaded.append(f"    > {skill_name}")
            except OSError as e:
                parts.append(f"\n[ERROR loading '{filename}']: {e}\n")

        if not loaded:
            return "\n[WARNING] None of the specified skills were found."

        loaded_list = "\n".join(loaded)
        print(f"{BLUE_BOLD}========= {len(loaded)} Skill(s) Loaded =========\n{loaded_list}\n====================================={RESET}\n")

        return "".join(parts)
