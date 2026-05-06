from __future__ import annotations

import ast as _ast
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any

SHELL_TIMEOUT: int = 60
MAX_FILE_BYTES: int = 200_000
_BINARY_MAGIC: list[bytes] = [
    b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"PK\x03\x04",
    b"MZ",      b"\x7fELF",     b"\x00\x00\x01\x00",
    b"%PDF",    b"BM",          b"\xcf\xfa\xed\xfe",
]
_BINARY_EXTS: frozenset[str] = frozenset({
    ".dll", ".exe", ".pdb", ".so", ".o", ".a", ".lib",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".7z", ".rar",
    ".pyc", ".pyo", ".whl", ".egg",
    ".pdf", ".docx", ".xlsx", ".pptx",
})

TOOLS_DEFINITIONS: list[dict] = [
    {
        "name": "read_files",
        "description": (
            "FAST FILE READ. Reads one or more text files in a single batch call. "
            "PREFER this over shell_execute for inspecting code. "
            "Binary files and files over 200 KB are skipped automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to read.",
                }
            },
            "required": ["paths"],
        },
    },
    {
        "name": "shell_execute",
        "description": (
            "RUN SHELL COMMAND. "
            "Use ONLY for: directory listing, grep, tests/builds, git, external processes. "
            "Do NOT use to read files — prefer read_files. "
            "Output truncated at 8 000 chars."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Full shell command to execute.",
                }
            },
            "required": ["command"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "CREATE OR OVERWRITE A FILE COMPLETELY. "
            "Use for saving code or docs. Creates intermediate dirs automatically. "
            "For small edits on existing files, prefer patch_file. "
            "CAUTION: sprint files (.yaml in /sprints/) are protected — "
            "content must be valid YAML with title, name and description."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string", "description": "File path to write."},
                "content": {"type": "string", "description": "Full file content."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "patch_file",
        "description": (
            "SURGICAL FILE EDIT. Replaces an exact text block without rewriting the whole file. "
            "Fails with a clear error if search_text is not found exactly once. "
            "PREFERRED for sprint files: edits only the needed field."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path":         {"type": "string", "description": "File path to edit."},
                "search_text":  {"type": "string", "description": "Exact text to find (must appear exactly once)."},
                "replace_text": {"type": "string", "description": "Text to replace it with."},
            },
            "required": ["path", "search_text", "replace_text"],
        },
    },
    {
        "name": "list_dir",
        "description": (
            "STRUCTURED DIRECTORY LISTING. Returns a file/folder tree with sizes. "
            "More efficient than shell ls/find for exploring project structure. "
            "Use depth to control tree depth (default 2)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path":        {"type": "string",  "description": "Root directory to list."},
                "depth":       {"type": "integer", "description": "Max depth (1-5, default 2)."},
                "show_hidden": {"type": "boolean", "description": "Include hidden files (default false)."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_text",
        "description": (
            "PATTERN SEARCH IN FILES. Native Python grep — no subprocess. "
            "Recursively searches a directory for a regex or literal pattern. "
            "Returns file + line number + matching line."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern":     {"type": "string",  "description": "Regex or literal string to search."},
                "directory":   {"type": "string",  "description": "Root directory for recursive search."},
                "file_glob":   {"type": "string",  "description": "Extension filter (e.g. '*.py', '*.ts'). Default: all text files."},
                "literal":     {"type": "boolean", "description": "If true, treat pattern as literal text (not regex). Default: false."},
                "max_results": {"type": "integer", "description": "Max results to return (default 50)."},
            },
            "required": ["pattern", "directory"],
        },
    },
    {
        "name": "context_store",
        "description": (
            "STORE LONG OUTPUT IN SQLITE — Context Mode. "
            "Runs a shell command; if output exceeds the inline limit, stores it in SQLite "
            "and returns only metadata (handle, size, preview). Use context_query to retrieve. "
            "Reduces ~98% of tokens for logs, build outputs and data dumps. "
            "PREFER over shell_execute when output is expected > 500 lines."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command":      {"type": "string",  "description": "Shell command to execute."},
                "tag":          {"type": "string",  "description": "Label to identify the result later (e.g. 'build-log')."},
                "inline_limit": {"type": "integer", "description": "Max chars to return inline; above this, stores in SQLite. Default: 2000."},
            },
            "required": ["command"],
        },
    },
    {
        "name": "context_query",
        "description": (
            "QUERY THE CONTEXT STORE. Search by keyword or return lines from a result "
            "stored by context_store. Use after context_store to get specific details "
            "without loading the full output."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "handle":    {"type": "string",  "description": "Handle returned by context_store (e.g. 'ctx_a1b2c3')."},
                "query":     {"type": "string",  "description": "Keyword or regex to search. Omit to return first lines."},
                "max_lines": {"type": "integer", "description": "Max lines to return. Default: 100."},
            },
            "required": ["handle"],
        },
    },
    {
        "name": "navigate_symbols",
        "description": (
            "SYMBOL NAVIGATION — Token Savior. "
            "Extracts functions, classes and methods from a file or directory using AST (Python) "
            "or structural regex (other languages) — without loading the full file. "
            "Returns name, line, signature and short docstring for each symbol. "
            "Use BEFORE read_files when locating a specific function or class."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path":         {"type": "string", "description": "File or directory to analyze."},
                "symbol_types": {"type": "array",  "items": {"type": "string"}, "description": "Types to extract: 'function', 'class', 'method'. Default: all."},
                "filter_name":  {"type": "string", "description": "Filter symbols whose name contains this text (case-insensitive). Optional."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_codebase",
        "description": (
            "SEMANTIC CODEBASE SEARCH — Gemini Context. "
            "Uses local embeddings (sentence-transformers) to find semantically relevant code chunks "
            "without reading full files. Returns top matches with file + line + snippet. "
            "Complements search_text (regex) with meaning-based search. "
            "NOTE: index is built on first call and cached in memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query":     {"type": "string", "description": "Natural language description of what you're looking for."},
                "directory": {"type": "string", "description": "Root directory of the codebase to index/search."},
                "top_k":     {"type": "integer", "description": "Number of chunks to return. Default: 5."},
                "file_glob": {"type": "string",  "description": "Extension filter (e.g. '*.py', '*.cs'). Default: common text files."},
            },
            "required": ["query", "directory"],
        },
    },
]


class NativeToolsManager:

    def get_tools(self) -> list[dict]:
        return TOOLS_DEFINITIONS

    def get_tools_cached(self) -> list[dict]:
        if not TOOLS_DEFINITIONS:
            return TOOLS_DEFINITIONS
        tools = [dict(t) for t in TOOLS_DEFINITIONS]
        tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
        return tools

    async def execute_tool(self, name: str, tool_input: dict) -> str:
        if not isinstance(tool_input, dict):
            tool_input = {}

        match name:
            case "read_files":
                return self._read_files(tool_input.get("paths", []))
            case "shell_execute":
                return self._shell_execute(tool_input.get("command", ""))
            case "write_file":
                return self._write_file(
                    tool_input.get("path", ""),
                    tool_input.get("content", ""),
                )
            case "patch_file":
                return self._patch_file(
                    tool_input.get("path", ""),
                    tool_input.get("search_text", ""),
                    tool_input.get("replace_text", ""),
                )
            case "list_dir":
                return self._list_dir(
                    tool_input.get("path", "."),
                    tool_input.get("depth", 2),
                    tool_input.get("show_hidden", False),
                )
            case "search_text":
                return self._search_text(
                    tool_input.get("pattern", ""),
                    tool_input.get("directory", "."),
                    tool_input.get("file_glob", "*"),
                    tool_input.get("literal", False),
                    tool_input.get("max_results", 50),
                )
            case "context_store":
                return self._context_store(
                    tool_input.get("command", ""),
                    tool_input.get("tag", ""),
                    tool_input.get("inline_limit", 2000),
                )
            case "context_query":
                return self._context_query(
                    tool_input.get("handle", ""),
                    tool_input.get("query", ""),
                    tool_input.get("max_lines", 100),
                )
            case "navigate_symbols":
                return self._navigate_symbols(
                    tool_input.get("path", ""),
                    tool_input.get("symbol_types", []),
                    tool_input.get("filter_name", ""),
                )
            case "search_codebase":
                return self._search_codebase(
                    tool_input.get("query", ""),
                    tool_input.get("directory", "."),
                    tool_input.get("top_k", 5),
                    tool_input.get("file_glob", ""),
                )
            case _:
                return f"Error: unknown native tool '{name}'."

    def _read_files(self, paths: list[str]) -> str:
        if not paths:
            return "Error: no paths provided."
        parts: list[str] = []
        for raw in paths:
            path = raw.strip()
            p = Path(path)
            if not p.exists():
                parts.append(f"--- NOT FOUND: {path} ---")
                continue
            if p.is_dir():
                parts.append(f"--- IS A DIRECTORY (use list_dir): {path} ---")
                continue
            if p.suffix.lower() in _BINARY_EXTS:
                parts.append(f"--- BINARY SKIPPED (ext): {path} ---")
                continue
            try:
                with p.open("rb") as fb:
                    header = fb.read(4)
                if any(header.startswith(magic) for magic in _BINARY_MAGIC):
                    parts.append(f"--- BINARY SKIPPED (magic): {path} ---")
                    continue
                size = p.stat().st_size
                if size > MAX_FILE_BYTES:
                    parts.append(
                        f"--- FILE TOO LARGE ({size:,} bytes > {MAX_FILE_BYTES:,}): {path} ---\n"
                        f"    Use search_text to find specific sections."
                    )
                    continue
                content = p.read_text(encoding="utf-8", errors="replace")
                parts.append(f"--- FILE: {path} ---\n{content}\n")
            except OSError as e:
                parts.append(f"--- ERROR ({path}): {e} ---")
        return "\n".join(parts) if parts else "No files read."

    _SPRINT_REQUIRED_FIELDS = ("title", "name", "description")

    def _is_sprint_file(self, p: Path) -> bool:
        try:
            parts = p.resolve().parts
            return p.suffix.lower() == ".yaml" and "sprints" in parts
        except Exception:
            return False

    def _validate_sprint_content(self, content: str, path: str) -> str | None:
        if not content or not content.strip():
            return (
                f"❌ Sprint protection: write_file blocked on '{path}'.\n"
                "   Content is EMPTY — likely truncated by token limit.\n"
                "   SOLUTION: Use shell_execute with heredoc, or patch_file for specific fields."
            )
        try:
            import yaml as _yaml
            data = _yaml.safe_load(content)
        except Exception as e:
            return (
                f"❌ Sprint protection: write_file blocked on '{path}'.\n"
                f"   Content is not valid YAML: {e}"
            )
        if not isinstance(data, dict):
            return (
                f"❌ Sprint protection: write_file blocked on '{path}'.\n"
                "   YAML content is not a dict."
            )
        missing = [f for f in self._SPRINT_REQUIRED_FIELDS if not data.get(f)]
        if missing:
            return (
                f"❌ Sprint protection: write_file blocked on '{path}'.\n"
                f"   Missing required fields: {missing}. "
                "Use patch_file to edit only the needed section."
            )
        return None

    def _write_file(self, path: str, content: str) -> str:
        if not path:
            return "Error: path not provided."
        if not content:
            return (
                "❌ write_file blocked: 'content' is EMPTY.\n"
                "   Likely truncated by token limit.\n"
                "   SOLUTION: Use shell_execute with heredoc."
            )
        p = Path(path)
        if self._is_sprint_file(p):
            error = self._validate_sprint_content(content, path)
            if error:
                return error
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"✅ File saved: '{path}' ({p.stat().st_size:,} bytes)."
        except OSError as e:
            return f"❌ Error writing '{path}': {e}"

    def _patch_file(self, path: str, search_text: str, replace_text: str) -> str:
        if not path or not search_text:
            return "Error: path and search_text are required."
        p = Path(path)
        if not p.exists():
            return f"Error: file '{path}' not found."
        try:
            original = p.read_text(encoding="utf-8", errors="replace")
            count = original.count(search_text)
            if count == 0:
                return f"❌ Patch failed: text not found in '{path}'."
            if count > 1:
                return (
                    f"❌ Ambiguous patch: search_text appears {count}x in '{path}'. "
                    "Provide a more specific excerpt."
                )
            patched = original.replace(search_text, replace_text, 1)
            if self._is_sprint_file(p):
                error = self._validate_sprint_content(patched, path)
                if error:
                    return error + "\n   Patch reverted. Original file unchanged."
            p.write_text(patched, encoding="utf-8")
            delta = len(patched) - len(original)
            sign = "+" if delta >= 0 else ""
            return f"✅ Patch applied to '{path}' ({sign}{delta} chars)."
        except OSError as e:
            return f"❌ Error patching '{path}': {e}"

    def _list_dir(self, path: str, depth: int, show_hidden: bool) -> str:
        root = Path(path)
        if not root.exists():
            return f"Error: path '{path}' not found."
        if not root.is_dir():
            return f"Error: '{path}' is not a directory."
        depth = max(1, min(depth or 2, 5))
        lines: list[str] = [f"📁 {root.resolve()}"]
        self._walk_dir(root, lines, prefix="", current=0, max_depth=depth, show_hidden=show_hidden)
        return "\n".join(lines)

    def _walk_dir(self, directory: Path, lines: list[str], prefix: str,
                  current: int, max_depth: int, show_hidden: bool) -> None:
        if current >= max_depth:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        except PermissionError:
            lines.append(f"{prefix}  [permission denied]")
            return
        entries = [e for e in entries if show_hidden or not e.name.startswith(".")]
        for i, entry in enumerate(entries):
            connector = "└── " if i == len(entries) - 1 else "├── "
            if entry.is_dir():
                lines.append(f"{prefix}{connector}📁 {entry.name}/")
                extension = "    " if i == len(entries) - 1 else "│   "
                self._walk_dir(entry, lines, prefix + extension, current + 1, max_depth, show_hidden)
            else:
                size = entry.stat().st_size
                size_str = (f"{size:,}b" if size < 1024
                            else f"{size/1024:.1f}KB" if size < 1_048_576
                            else f"{size/1_048_576:.1f}MB")
                lines.append(f"{prefix}{connector}{entry.name}  [{size_str}]")

    def _search_text(self, pattern: str, directory: str, file_glob: str,
                     literal: bool, max_results: int) -> str:
        if not pattern:
            return "Error: pattern not provided."
        root = Path(directory)
        if not root.exists():
            return f"Error: directory '{directory}' not found."
        max_results = max(1, min(max_results or 50, 500))
        glob = file_glob or "*"
        try:
            regex = re.compile(re.escape(pattern) if literal else pattern, re.IGNORECASE)
        except re.error as e:
            return f"Error: invalid regex — {e}"
        results: list[str] = []
        files_searched = 0
        for file_path in sorted(root.rglob(glob)):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() in _BINARY_EXTS:
                continue
            if file_path.stat().st_size > MAX_FILE_BYTES * 2:
                continue
            try:
                for lineno, line in enumerate(
                    file_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
                ):
                    if regex.search(line):
                        rel = file_path.relative_to(root)
                        results.append(f"{rel}:{lineno}: {line.strip()}")
                        if len(results) >= max_results:
                            break
                files_searched += 1
            except OSError:
                continue
            if len(results) >= max_results:
                break
        if not results:
            return f"No results for '{pattern}' in {files_searched} file(s)."
        header = f"🔍 {len(results)} result(s) for '{pattern}' [{files_searched} file(s) searched]:\n"
        suffix = f"\n… (limit of {max_results} reached)" if len(results) == max_results else ""
        return header + "\n".join(results) + suffix

    _ctx_db_path: Path | None = None
    _ctx_cache: dict[str, str] = {}

    @classmethod
    def _ctx_db(cls) -> sqlite3.Connection:
        if cls._ctx_db_path is None:
            base = Path(__file__).parent.parent / "executions"
            base.mkdir(parents=True, exist_ok=True)
            cls._ctx_db_path = base / "context_store.db"
        conn = sqlite3.connect(str(cls._ctx_db_path))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ctx ("
            "  handle TEXT PRIMARY KEY,"
            "  tag    TEXT,"
            "  command TEXT,"
            "  content TEXT,"
            "  created_at TEXT DEFAULT (datetime('now'))"
            ")"
        )
        conn.commit()
        return conn

    def _context_store(self, command: str, tag: str, inline_limit: int) -> str:
        if not command or not command.strip():
            return "❌ context_store: 'command' is empty."
        inline_limit = max(200, min(inline_limit or 2000, 10_000))
        output = self._shell_execute(command)
        if len(output) <= inline_limit:
            return f"[context_store] Inline output ({len(output)} chars):\n{output}"
        handle = "ctx_" + hashlib.sha1(output.encode()).hexdigest()[:8]
        tag_label = tag or command[:60]
        try:
            conn = self._ctx_db()
            conn.execute(
                "INSERT OR REPLACE INTO ctx (handle, tag, command, content) VALUES (?,?,?,?)",
                (handle, tag_label, command, output),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            return f"❌ context_store: SQLite write failed: {e}\nRaw output (truncated):\n{output[:inline_limit]}"
        self._ctx_cache[handle] = output
        lines = output.splitlines()
        preview = "\n".join(lines[:15])
        return (
            f"[context_store] Output stored out-of-context.\n"
            f"  Handle : {handle}\n"
            f"  Tag    : {tag_label}\n"
            f"  Size   : {len(output):,} chars | {len(lines):,} lines\n"
            f"  Preview (15 lines):\n{preview}\n"
            f"  ↳ Use context_query(handle='{handle}', query='...') to search."
        )

    def _context_query(self, handle: str, query: str, max_lines: int) -> str:
        if not handle:
            return "❌ context_query: 'handle' required."
        max_lines = max(1, min(max_lines or 100, 2000))
        content = self._ctx_cache.get(handle)
        if content is None:
            try:
                conn = self._ctx_db()
                row = conn.execute("SELECT content FROM ctx WHERE handle=?", (handle,)).fetchone()
                conn.close()
                if not row:
                    return f"❌ context_query: handle '{handle}' not found."
                content = row[0]
                self._ctx_cache[handle] = content
            except Exception as e:
                return f"❌ context_query: SQLite error: {e}"
        lines = content.splitlines()
        if not query:
            result = "\n".join(lines[:max_lines])
            suffix = f"\n… ({len(lines) - max_lines} more lines)" if len(lines) > max_lines else ""
            return f"[context_query] First {min(max_lines, len(lines))} lines of '{handle}':\n{result}{suffix}"
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            pattern = re.compile(re.escape(query), re.IGNORECASE)
        matched = [(i + 1, line) for i, line in enumerate(lines) if pattern.search(line)]
        if not matched:
            return f"[context_query] No lines match '{query}' in '{handle}' ({len(lines)} lines total)."
        result_lines = [f"{lineno:>6}: {line}" for lineno, line in matched[:max_lines]]
        suffix = f"\n… ({len(matched) - max_lines} more results)" if len(matched) > max_lines else ""
        return (
            f"[context_query] {len(matched)} line(s) matching '{query}' in '{handle}':\n"
            + "\n".join(result_lines) + suffix
        )

    def _navigate_symbols(self, path: str, symbol_types: list[str], filter_name: str) -> str:
        if not path:
            return "❌ navigate_symbols: 'path' required."
        p = Path(path)
        if not p.exists():
            return f"❌ navigate_symbols: '{path}' not found."
        wanted = set(symbol_types) if symbol_types else {"function", "class", "method"}
        filter_lower = filter_name.lower() if filter_name else ""
        symbols: list[dict[str, Any]] = []
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() not in _BINARY_EXTS and f.stat().st_size < MAX_FILE_BYTES:
                    symbols.extend(self._extract_symbols(f, wanted, filter_lower))
        else:
            symbols = self._extract_symbols(p, wanted, filter_lower)
        if not symbols:
            what = f" containing '{filter_name}'" if filter_name else ""
            return f"No symbols{what} found in '{path}'."
        lines = [f"{'Line':>6}  {'Type':<10} {'Name':<40} Signature"]
        lines.append("-" * 80)
        for s in symbols:
            sig = s["signature"]
            if len(sig) > 50:
                sig = sig[:47] + "..."
            lines.append(f"{s['line']:>6}  {s['kind']:<10} {s['name']:<40} {sig}")
            if s.get("doc"):
                lines.append(f"{'':>6}  {'':10} {'':40} # {s['doc'][:60]}")
        return f"[navigate_symbols] {len(symbols)} symbol(s) in '{path}':\n" + "\n".join(lines)

    def _extract_symbols(self, path: Path, wanted: set[str], filter_lower: str) -> list[dict[str, Any]]:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        ext = path.suffix.lower()
        rel = str(path)
        if ext == ".py":
            return self._extract_python_symbols(source, rel, wanted, filter_lower)
        return self._extract_generic_symbols(source, rel, ext, wanted, filter_lower)

    def _extract_python_symbols(self, source: str, rel: str, wanted: set[str],
                                 filter_lower: str) -> list[dict[str, Any]]:
        symbols: list[dict[str, Any]] = []
        try:
            tree = _ast.parse(source)
        except SyntaxError:
            return []
        for node in _ast.walk(tree):
            if isinstance(node, _ast.ClassDef) and "class" in wanted:
                name = node.name
                if filter_lower and filter_lower not in name.lower():
                    continue
                doc = _ast.get_docstring(node) or ""
                symbols.append({"line": node.lineno, "kind": "class", "name": name,
                                 "signature": f"class {name}", "doc": doc[:80], "file": rel})
                if "method" in wanted:
                    for item in node.body:
                        if isinstance(item, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                            mname = item.name
                            if filter_lower and filter_lower not in mname.lower():
                                continue
                            sig = self._py_sig(item)
                            mdoc = _ast.get_docstring(item) or ""
                            symbols.append({"line": item.lineno, "kind": "method",
                                            "name": f"{name}.{mname}", "signature": sig,
                                            "doc": mdoc[:80], "file": rel})
            elif isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and "function" in wanted:
                name = node.name
                if filter_lower and filter_lower not in name.lower():
                    continue
                sig = self._py_sig(node)
                doc = _ast.get_docstring(node) or ""
                symbols.append({"line": node.lineno, "kind": "function", "name": name,
                                 "signature": sig, "doc": doc[:80], "file": rel})
        symbols.sort(key=lambda s: s["line"])
        return symbols

    @staticmethod
    def _py_sig(node: _ast.FunctionDef | _ast.AsyncFunctionDef) -> str:
        args = node.args
        parts: list[str] = []
        defaults_offset = len(args.args) - len(args.defaults)
        for i, arg in enumerate(args.args):
            default_idx = i - defaults_offset
            if default_idx >= 0:
                try:
                    default_val = _ast.unparse(args.defaults[default_idx])
                    parts.append(f"{arg.arg}={default_val}")
                except Exception:
                    parts.append(arg.arg)
            else:
                parts.append(arg.arg)
        if args.vararg:
            parts.append(f"*{args.vararg.arg}")
        for kw in args.kwonlyargs:
            parts.append(kw.arg)
        if args.kwarg:
            parts.append(f"**{args.kwarg.arg}")
        prefix = "async def" if isinstance(node, _ast.AsyncFunctionDef) else "def"
        return f"{prefix} {node.name}({', '.join(parts)})"

    _SYMBOL_PATTERNS: dict[str, list[tuple[str, str]]] = {
        ".cs":   [
            ("class",  r"^\s*(?:public|private|protected|internal|static|abstract|sealed)*\s*class\s+(\w+)"),
            ("method", r"^\s*(?:public|private|protected|internal|static|virtual|override|async)*\s+\w[\w<>\[\],\s]*\s+(\w+)\s*\("),
        ],
        ".ts":   [
            ("class",    r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)"),
            ("function", r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*[\(<]"),
            ("method",   r"^\s*(?:public|private|protected|static|async|override)*\s+(\w+)\s*[\(<]"),
        ],
        ".js":   [
            ("class",    r"^\s*(?:export\s+)?class\s+(\w+)"),
            ("function", r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\("),
        ],
        ".java": [
            ("class",  r"^\s*(?:public|private|protected|abstract|final)*\s*class\s+(\w+)"),
            ("method", r"^\s*(?:public|private|protected|static|final|abstract|synchronized|native)*\s+\w[\w<>\[\],\s]*\s+(\w+)\s*\("),
        ],
        ".kt":   [
            ("class",    r"^\s*(?:data\s+|sealed\s+|abstract\s+|open\s+)?class\s+(\w+)"),
            ("function", r"^\s*(?:override\s+)?(?:suspend\s+)?fun\s+(\w+)\s*[\(<]"),
        ],
        ".swift": [
            ("class",    r"^\s*(?:public|private|internal|open|final)*\s*class\s+(\w+)"),
            ("function", r"^\s*(?:public|private|internal|open|override|static|class|mutating|final)*\s*func\s+(\w+)\s*[\(<]"),
        ],
        ".go":   [
            ("function", r"^\s*func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\("),
        ],
        ".dart": [
            ("class",    r"^\s*(?:abstract\s+)?class\s+(\w+)"),
            ("function", r"^\s*(?:static\s+)?(?:Future|void|String|int|bool|double|List|Map|dynamic|\w+)\s+(\w+)\s*\("),
        ],
    }

    def _extract_generic_symbols(self, source: str, rel: str, ext: str, wanted: set[str],
                                  filter_lower: str) -> list[dict[str, Any]]:
        patterns = self._SYMBOL_PATTERNS.get(ext, [])
        if not patterns:
            return []
        symbols: list[dict[str, Any]] = []
        lines = source.splitlines()
        for lineno, line in enumerate(lines, start=1):
            for kind, pattern in patterns:
                if kind not in wanted:
                    continue
                m = re.match(pattern, line)
                if m:
                    name = m.group(1)
                    if filter_lower and filter_lower not in name.lower():
                        continue
                    symbols.append({"line": lineno, "kind": kind, "name": name,
                                    "signature": line.strip(), "doc": "", "file": rel})
        return symbols

    _cb_index: dict[str, tuple[list[dict], list[list[float]], str]] = {}
    _cb_model = None
    _cb_available: bool | None = None
    CHUNK_SIZE = 40
    CHUNK_OVERLAP = 8

    @classmethod
    def _load_embed_model(cls) -> bool:
        if cls._cb_available is not None:
            return cls._cb_available
        try:
            import logging as _logging
            _logging.getLogger("sentence_transformers").setLevel(_logging.ERROR)
            _logging.getLogger("transformers").setLevel(_logging.ERROR)
            os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from sentence_transformers import SentenceTransformer
            cls._cb_model = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=False)
            cls._cb_available = True
        except ImportError:
            cls._cb_available = False
        return cls._cb_available

    @classmethod
    def _embed_texts(cls, texts: list[str]) -> list[list[float]]:
        vecs = cls._cb_model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return [v.tolist() for v in vecs]

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return dot / (na * nb) if na and nb else 0.0

    def _dir_hash(self, directory: Path, glob: str) -> str:
        files = sorted(
            f for f in directory.rglob(glob or "*")
            if f.is_file() and not self._is_ignored_path(f)
        )
        sig = ";".join(f"{f}:{f.stat().st_mtime}" for f in files)
        return hashlib.md5(sig.encode()).hexdigest()[:12]

    _IGNORED_DIRS: frozenset[str] = frozenset({
        ".venv", "venv", ".env", "env",
        "node_modules", ".git",
        "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        "executions", "git-cache", "logs",
        "dist", "build", ".dist", "out",
        "site-packages",
    })

    def _is_ignored_path(self, fpath: Path) -> bool:
        return any(part in self._IGNORED_DIRS for part in fpath.parts)

    def _build_chunks(self, directory: Path, glob: str) -> list[dict]:
        exts_text = frozenset({
            ".py", ".ts", ".js", ".cs", ".java", ".kt", ".swift", ".go",
            ".dart", ".md", ".txt", ".yaml", ".json", ".html", ".css",
        })
        chunks: list[dict] = []
        pattern = glob or "*"
        for fpath in sorted(directory.rglob(pattern)):
            if not fpath.is_file():
                continue
            if self._is_ignored_path(fpath):
                continue
            if fpath.suffix.lower() in _BINARY_EXTS:
                continue
            if glob == "" and fpath.suffix.lower() not in exts_text:
                continue
            if fpath.stat().st_size > MAX_FILE_BYTES:
                continue
            try:
                lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            step = max(1, self.CHUNK_SIZE - self.CHUNK_OVERLAP)
            for start in range(0, len(lines), step):
                end = min(start + self.CHUNK_SIZE, len(lines))
                text = "\n".join(lines[start:end])
                if not text.strip():
                    continue
                chunks.append({"file": str(fpath), "line_start": start + 1,
                                "line_end": end, "text": text})
        return chunks

    def _search_codebase(self, query: str, directory: str, top_k: int, file_glob: str) -> str:
        if not query:
            return "❌ search_codebase: 'query' required."
        if not self._load_embed_model():
            return (
                "❌ search_codebase: sentence-transformers not installed.\n"
                "   Run: pip install sentence-transformers"
            )
        root = Path(directory)
        if not root.exists() or not root.is_dir():
            return f"❌ search_codebase: directory '{directory}' not found."
        top_k = max(1, min(top_k or 5, 20))
        glob = file_glob or ""
        dir_key = str(root.resolve()) + "|" + glob
        current_hash = self._dir_hash(root, glob)
        cached = self._cb_index.get(dir_key)
        if cached is None or cached[2] != current_hash:
            print(f"[search_codebase] Indexing '{directory}'...", end=" ", flush=True)
            chunks = self._build_chunks(root, glob)
            if not chunks:
                return f"No indexable files found in '{directory}'."
            texts = [c["text"] for c in chunks]
            embeddings = self._embed_texts(texts)
            self._cb_index[dir_key] = (chunks, embeddings, current_hash)
            print(f"{len(chunks)} chunks ✅")
        else:
            chunks, embeddings, _ = cached
        query_vec = self._embed_texts([query])[0]
        scored = [(i, self._cosine(query_vec, emb)) for i, emb in enumerate(embeddings)]
        scored.sort(key=lambda x: x[1], reverse=True)
        results: list[str] = []
        seen_files: set[str] = set()
        for idx, score in scored[:top_k * 3]:
            if len(results) >= top_k:
                break
            if score < 0.15:
                break
            chunk = chunks[idx]
            file_key = f"{chunk['file']}:{chunk['line_start']}"
            if file_key in seen_files:
                continue
            seen_files.add(file_key)
            rel = (Path(chunk["file"]).relative_to(root.resolve())
                   if root.resolve() in Path(chunk["file"]).parents else chunk["file"])
            preview = chunk["text"]
            if len(preview) > 600:
                preview = preview[:600] + "\n…"
            results.append(
                f"[score={score:.2f}] {rel} (lines {chunk['line_start']}–{chunk['line_end']}):\n"
                f"```\n{preview}\n```"
            )
        if not results:
            return f"[search_codebase] No relevant chunks found for: '{query}'"
        return (
            f"[search_codebase] Top {len(results)} chunks for '{query}':\n\n"
            + "\n\n---\n\n".join(results)
        )

    def _shell_execute(self, command: str) -> str:
        if not command or not command.strip():
            return "❌ shell_execute blocked: 'command' is empty."

        command = command.strip()

        # --- LOGICA DE RESOLUÇÃO DE CAMINHO ---
        # Se o comando for 'coia', nós trocamos pelo caminho real do venv + app.py
        if command.startswith("coia"):
            # Detecta o diretório src do projeto
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

            if sys.platform == "win32":
                venv_python = os.path.join(base_path, ".venv", "Scripts", "python.exe")
            else:
                venv_python = os.path.join(base_path, ".venv", "bin", "python3")

            app_py = os.path.join(base_path, "app.py")

            # Substitui 'coia' pelo comando completo
            command = command.replace("coia", f'"{venv_python}" "{app_py}"', 1)

        try:
            # Usamos shell=True no Windows para suportar comandos nativos do CMD se necessário
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True, 
                timeout=SHELL_TIMEOUT
            )

            output = (result.stdout or "") + (result.stderr or "")

            if result.returncode != 0 and not output:
                return f"❌ Command failed with exit code {result.returncode}."

            if not output:
                return f"✅ Command executed (exit {result.returncode}, no output)."

            if len(output) > 8_000:
                output = output[:8_000] + f"\n… [output truncated — {len(output):,} chars total]"

            return output

        except subprocess.TimeoutExpired:
            return f"❌ Timeout: command exceeded {SHELL_TIMEOUT}s."
        except OSError as e:
            return f"❌ Shell error: {e}"
