from __future__ import annotations
import ast, hashlib, json, math, os, re, sqlite3, subprocess, sys, warnings
from pathlib import Path
from typing import Any

TIMEOUT = 60
MAX_BYTES = 200_000
BIN_EXTS = {'.exe', '.dll', '.so', '.pyc', '.png', '.jpg', '.zip', '.pdf', '.docx'}

TOOLS = [
    {
        "name": "read_files",
        "description": "Read text files. Skip binary or >200KB.",
        "input_schema": {
            "type": "object",
            "properties": {"paths": {"type": "array", "items": {"type": "string"}}},
            "required": ["paths"]
        }
    },
    {
        "name": "shell_execute",
        "description": "Run Windows CMD command. Use for tests, git, dir. Max 8k chars output.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"]
        }
    },
    {
        "name": "write_file",
        "description": "Create/Overwrite file. Auto-creates dirs.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]
        }
    },
    {
        "name": "patch_file",
        "description": "Surgical edit. Replace exact text block once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "search": {"type": "string"},
                "replace": {"type": "string"}
            },
            "required": ["path", "search", "replace"]
        }
    },
    {
        "name": "list_dir",
        "description": "Tree view of directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "depth": {"type": "integer", "default": 2}
            },
            "required": ["path"]
        }
    },
    {
        "name": "search_text",
        "description": "Regex search in files (Python native).",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "dir": {"type": "string"},
                "glob": {"type": "string", "default": "*"}
            },
            "required": ["pattern", "dir"]
        }
    }
]

class NativeToolsManager:
    def get_tools(self) -> list[dict]:
        return TOOLS

    async def execute_tool(self, name: str, args: dict) -> str:
        try:
            match name:
                case "read_files": return self._read(args.get("paths", []))
                case "shell_execute": return self._shell(args.get("command", ""))
                case "write_file": return self._write(args.get("path", ""), args.get("content", ""))
                case "patch_file": return self._patch(args.get("path", ""), args.get("search", ""), args.get("replace", ""))
                case "list_dir": return self._list(args.get("path", "."), args.get("depth", 2))
                case "search_text": return self._search(args.get("pattern", ""), args.get("dir", "."), args.get("glob", "*"))
                case _: return f"Error: Unknown tool {name}"
        except Exception as e:
            return f"Error executing {name}: {str(e)}"

    def _read(self, paths: list[str]) -> str:
        res = []
        for p in paths:
            path = Path(p)
            if not path.exists(): res.append(f"Not found: {p}")
            elif path.suffix.lower() in BIN_EXTS: res.append(f"Skip binary: {p}")
            elif path.stat().st_size > MAX_BYTES: res.append(f"Too large: {p}")
            else:
                content = path.read_text(encoding="utf-8", errors="replace")
                res.append(f"--- {p} ---\n{content}")
        return "\n".join(res)

    def _shell(self, cmd: str) -> str:
        if not cmd.strip(): return "Empty command."
        
        # Windows venv resolution logic for 'coia'
        if cmd.startswith("coia"):
            root = Path(__file__).parent.parent
            py = root / ".venv" / "Scripts" / "python.exe"
            app = root / "app.py"
            cmd = cmd.replace("coia", f'"{py}" "{app}"', 1)

        try:
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=TIMEOUT)
            out = (proc.stdout + proc.stderr).strip()
            if not out: return f"Done (Exit {proc.returncode})"
            return out[:8000] + ("..." if len(out) > 8000 else "")
        except subprocess.TimeoutExpired: return "Error: Timeout"

    def _write(self, path: str, content: str) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Saved {path} ({p.stat().st_size} bytes)"

    def _patch(self, path: str, search: str, replace: str) -> str:
        p = Path(path)
        if not p.exists(): return "File not found"
        text = p.read_text(encoding="utf-8")
        if text.count(search) != 1: return f"Error: Search text found {text.count(search)} times (need 1)."
        p.write_text(text.replace(search, replace, 1), encoding="utf-8")
        return f"Patched {path}"

    def _list(self, path: str, depth: int) -> str:
        root = Path(path)
        if not root.is_dir(): return "Not a directory"
        def walk(d, cur_depth):
            if cur_depth > depth: return ""
            tree = ""
            for item in sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
                indent = "  " * cur_depth
                icon = "f" if item.is_file() else "d"
                tree += f"{indent}[{icon}] {item.name}\n"
                if item.is_dir(): tree += walk(item, cur_depth + 1)
            return tree
        return f"Tree: {root.absolute()}\n" + walk(root, 0)

    def _search(self, pattern: str, directory: str, glob_pat: str) -> str:
        root = Path(directory)
        rx = re.compile(pattern, re.I)
        hits = []
        for f in root.rglob(glob_pat):
            if f.is_file() and f.suffix.lower() not in BIN_EXTS:
                try:
                    for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines()):
                        if rx.search(line): hits.append(f"{f.name}:{i+1}: {line.strip()}")
                except: continue
            if len(hits) > 50: break
        return "\n".join(hits) or "No matches."