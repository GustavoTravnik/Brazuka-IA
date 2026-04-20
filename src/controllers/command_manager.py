import os


class CommandManager:
    def __init__(self, commands_path: str | None = None) -> None:
        if commands_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            commands_path = os.path.join(base_dir, "commands")
        self.commands_path = commands_path

    def get_commands(self, command_name: str) -> str | None:
        file_path = os.path.join(self.commands_path, f"{command_name}.md")
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            return f"Erro ao ler comando '{command_name}': {e}"
