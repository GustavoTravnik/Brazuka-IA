"""
NativeToolsManager — v2.0  (performance-first)
================================================
Ferramentas nativas altamente otimizadas para uso pela IA.

Otimizações aplicadas:
  - read_files    : leitura em batch com detecção rápida de binário via magic bytes
                    + limite de tamanho por arquivo para evitar context flood
  - shell_execute : timeout configurável, prefixo `rtk` automático, saída truncada
  - write_file    : criação segura de diretórios + confirmação de bytes escritos
  - patch_file    : NOVO — aplica diffs parciais (search/replace) sem reescrever o arquivo inteiro
  - list_dir      : NOVO — listagem estruturada de diretório (substitui `ls` ad-hoc no shell)
  - search_text   : NOVO — grep nativo em Python; rápido e sem subprocesso
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

# ── Configurações globais ────────────────────────────────────────────────────
SHELL_TIMEOUT: int = 60          # segundos
MAX_FILE_BYTES: int = 200_000    # ~200 KB por arquivo; evita flood de contexto

# Magic bytes para detecção de binário (os primeiros 4 bytes do arquivo)
_BINARY_MAGIC: list[bytes] = [
    b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"PK\x03\x04",   # PNG, JPEG, GIF, ZIP
    b"MZ",      b"\x7fELF",     b"\x00\x00\x01\x00",        # EXE/DLL, ELF, ICO
    b"%PDF",    b"BM",          b"\xcf\xfa\xed\xfe",         # PDF, BMP, Mach-O
]
_BINARY_EXTS: frozenset[str] = frozenset({
    ".dll", ".exe", ".pdb", ".so", ".o", ".a", ".lib",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".7z", ".rar",
    ".pyc", ".pyo", ".whl", ".egg",
    ".pdf", ".docx", ".xlsx", ".pptx",
})

# ── Schemas de ferramentas (definição para a API da Anthropic) ───────────────
TOOLS_DEFINITIONS: list[dict] = [
    {
        "name": "read_files",
        "description": (
            "LEITURA RÁPIDA DE ARQUIVOS. Lê um ou mais arquivos de texto em batch de uma só chamada. "
            "PRIORIZE esta ferramenta antes de qualquer shell_execute para investigar código. "
            "Arquivos binários e acima de 200 KB são ignorados automaticamente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de caminhos dos arquivos a serem lidos.",
                }
            },
            "required": ["paths"],
        },
    },
    {
        "name": "shell_execute",
        "description": (
            "EXECUÇÃO DE COMANDOS NO TERMINAL. "
            "Use SOMENTE para: listar diretórios (ls, find), buscar padrões (grep), "
            "executar testes/builds, comandos git ou outros processos externos. "
            "NÃO use para ler arquivos — prefira read_files. "
            "Comandos longos são truncados após 8 000 chars de saída."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Comando completo a ser executado no shell.",
                }
            },
            "required": ["command"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "CRIA OU SOBRESCREVE UM ARQUIVO COMPLETAMENTE. "
            "Use para salvar código ou documentação. "
            "Cria automaticamente os diretórios intermediários. "
            "Para alterações pontuais em arquivos já existentes, prefira patch_file. "
            "ATENÇÃO: arquivos de sprint (.yaml em /sprints/) são protegidos — "
            "o conteúdo deve ser YAML válido contendo title, name e description. "
            "Conteúdo vazio ou sem esses campos é bloqueado automaticamente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string", "description": "Caminho do arquivo a ser escrito."},
                "content": {"type": "string", "description": "Conteúdo completo do arquivo."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "patch_file",
        "description": (
            "EDIÇÃO CIRÚRGICA DE ARQUIVO. Substitui um trecho exato de texto sem reescrever o arquivo inteiro. "
            "Ideal para correções pontuais: muda apenas o bloco search → replace. "
            "Falha com erro claro se search_text não for encontrado (exatamente 1 vez). "
            "PREFERIDO para arquivos de sprint: altera só o campo necessário (status, tasks, updates) "
            "sem risco de apagar o restante do arquivo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path":        {"type": "string", "description": "Caminho do arquivo a editar."},
                "search_text": {"type": "string", "description": "Trecho EXATO a ser localizado."},
                "replace_text": {"type": "string", "description": "Texto que substituirá o trecho."},
            },
            "required": ["path", "search_text", "replace_text"],
        },
    },
    {
        "name": "list_dir",
        "description": (
            "LISTAGEM ESTRUTURADA DE DIRETÓRIO. Retorna árvore de arquivos/pastas "
            "com tamanho e tipo. Mais eficiente que shell ls/find para explorar a estrutura do projeto. "
            "Use depth para controlar a profundidade (padrão 2)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path":  {"type": "string",  "description": "Diretório raiz a listar."},
                "depth": {"type": "integer", "description": "Profundidade máxima (1-5, padrão 2)."},
                "show_hidden": {"type": "boolean", "description": "Incluir arquivos/pastas ocultos (padrão false)."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_text",
        "description": (
            "BUSCA DE PADRÃO EM ARQUIVOS. Grep nativo em Python — sem subprocesso. "
            "Busca recursivamente por um padrão (regex ou literal) em todos os arquivos "
            "de um diretório. Retorna arquivo + número de linha + linha correspondente. "
            "Use para encontrar usos de funções, imports, TODOs, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern":   {"type": "string",  "description": "Expressão regex ou texto literal a buscar."},
                "directory": {"type": "string",  "description": "Diretório raiz para busca recursiva."},
                "file_glob": {"type": "string",  "description": "Filtro de extensão (ex: '*.py', '*.ts'). Padrão: todos os arquivos de texto."},
                "literal":   {"type": "boolean", "description": "Se true, trata pattern como texto literal (não regex). Padrão: false."},
                "max_results": {"type": "integer", "description": "Limite de resultados retornados (padrão 50)."},
            },
            "required": ["pattern", "directory"],
        },
    },
]


class NativeToolsManager:
    """Gerenciador de ferramentas nativas da IA — v2.0."""

    # ── Interface pública ────────────────────────────────────────────────────

    def get_tools(self) -> list[dict]:
        return TOOLS_DEFINITIONS

    async def execute_tool(self, name: str, tool_input: dict) -> str:
        # Garante que tool_input é sempre um dict (nunca None ou outro tipo)
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
            case _:
                return f"Erro: ferramenta nativa '{name}' não reconhecida."

    # ── Implementações ───────────────────────────────────────────────────────

    def _read_files(self, paths: list[str]) -> str:
        if not paths:
            return "Erro: nenhum caminho informado."
        parts: list[str] = []
        for raw in paths:
            path = raw.strip()
            p = Path(path)
            if not p.exists():
                parts.append(f"--- NÃO ENCONTRADO: {path} ---")
                continue
            if p.is_dir():
                parts.append(f"--- É UM DIRETÓRIO (use list_dir): {path} ---")
                continue
            if p.suffix.lower() in _BINARY_EXTS:
                parts.append(f"--- BINÁRIO IGNORADO (ext): {path} ---")
                continue
            try:
                # Checagem rápida por magic bytes sem ler o arquivo todo
                with p.open("rb") as fb:
                    header = fb.read(4)
                if any(header.startswith(magic) for magic in _BINARY_MAGIC):
                    parts.append(f"--- BINÁRIO IGNORADO (magic): {path} ---")
                    continue
                size = p.stat().st_size
                if size > MAX_FILE_BYTES:
                    parts.append(
                        f"--- ARQUIVO MUITO GRANDE ({size:,} bytes > {MAX_FILE_BYTES:,}): {path} ---\n"
                        f"    Use search_text para localizar trechos específicos."
                    )
                    continue
                content = p.read_text(encoding="utf-8", errors="replace")
                parts.append(f"--- FILE: {path} ---\n{content}\n")
            except OSError as e:
                parts.append(f"--- ERRO ({path}): {e} ---")
        return "\n".join(parts) if parts else "Nenhum arquivo lido."

    # Campos obrigatórios que todo YAML de sprint deve conter
    _SPRINT_REQUIRED_FIELDS = ("title", "name", "description")

    def _is_sprint_file(self, p: Path) -> bool:
        """Retorna True se o arquivo é um YAML dentro do diretório de sprints."""
        try:
            parts = p.resolve().parts
            return p.suffix.lower() == ".yaml" and "sprints" in parts
        except Exception:
            return False

    def _validate_sprint_content(self, content: str, path: str) -> str | None:
        """
        Valida o conteúdo antes de sobrescrever um arquivo de sprint.
        Retorna mensagem de erro se inválido, None se ok.
        """
        if not content or not content.strip():
            return (
                f"❌ Proteção de sprint: write_file bloqueado em '{path}'.\n"
                "   O conteúdo está VAZIO. Isso geralmente ocorre porque o conteúdo era grande demais\n"
                "   e foi truncado pelo limite de tokens da API antes de chegar aqui.\n"
                "   SOLUÇÃO: Use shell_execute com heredoc para escrever o arquivo:\n"
                "   shell_execute: cat > /caminho/arquivo.yaml << 'HEREDOC'\\n<conteudo>\\nHEREDOC\n"
                "   Ou use patch_file para alterar apenas campos específicos (status, tasks, updates)."
            )

        try:
            import yaml as _yaml
            data = _yaml.safe_load(content)
        except Exception as e:
            return (
                f"❌ Proteção de sprint: write_file bloqueado em '{path}'.\n"
                f"   O conteúdo não é um YAML válido: {e}\n"
                "   Corrija o YAML antes de salvar."
            )

        if not isinstance(data, dict):
            return (
                f"❌ Proteção de sprint: write_file bloqueado em '{path}'.\n"
                "   O conteúdo YAML não é um objeto (dict). Estrutura inválida."
            )

        missing = [f for f in self._SPRINT_REQUIRED_FIELDS if not data.get(f)]
        if missing:
            return (
                f"❌ Proteção de sprint: write_file bloqueado em '{path}'.\n"
                f"   Campos obrigatórios ausentes ou vazios: {missing}.\n"
                "   Todo arquivo de sprint deve conter: title, name e description.\n"
                "   Use patch_file para alterar apenas o trecho necessário sem risco de perder dados."
            )

        return None  # conteúdo válido

    def _write_file(self, path: str, content: str) -> str:
        if not path:
            return "Erro: caminho não informado."
        if not content:
            return (
                "❌ write_file bloqueado: o parâmetro 'content' chegou VAZIO.\n"
                "   Causa provável: o conteúdo era grande demais e foi truncado pelo limite de tokens.\n"
                "   SOLUÇÃO: Use shell_execute com heredoc:\n"
                "   cat > /caminho/arquivo << 'HEREDOC'\\n<conteudo>\\nHEREDOC"
            )
        p = Path(path)

        # Proteção: arquivos de sprint nunca podem ser sobrescritos com conteúdo inválido
        if self._is_sprint_file(p):
            error = self._validate_sprint_content(content, path)
            if error:
                return error

        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"✅ Arquivo salvo: '{path}' ({p.stat().st_size:,} bytes)."
        except OSError as e:
            return f"❌ Erro ao escrever '{path}': {e}"

    def _patch_file(self, path: str, search_text: str, replace_text: str) -> str:
        if not path or not search_text:
            return "Erro: path e search_text são obrigatórios."
        p = Path(path)
        if not p.exists():
            return f"Erro: arquivo '{path}' não encontrado."
        try:
            original = p.read_text(encoding="utf-8", errors="replace")
            count = original.count(search_text)
            if count == 0:
                return f"❌ Patch falhou: trecho não encontrado em '{path}'."
            if count > 1:
                return (
                    f"❌ Patch ambíguo: search_text aparece {count}x em '{path}'. "
                    "Forneça um trecho mais específico."
                )
            patched = original.replace(search_text, replace_text, 1)

            # Proteção: valida o resultado antes de gravar em arquivos de sprint
            if self._is_sprint_file(p):
                error = self._validate_sprint_content(patched, path)
                if error:
                    return (
                        error + "\n"
                        "   O patch foi revertido. O arquivo original não foi modificado."
                    )

            p.write_text(patched, encoding="utf-8")
            delta = len(patched) - len(original)
            sign = "+" if delta >= 0 else ""
            return f"✅ Patch aplicado em '{path}' ({sign}{delta} chars)."
        except OSError as e:
            return f"❌ Erro ao aplicar patch em '{path}': {e}"

    def _list_dir(self, path: str, depth: int, show_hidden: bool) -> str:
        root = Path(path)
        if not root.exists():
            return f"Erro: caminho '{path}' não encontrado."
        if not root.is_dir():
            return f"Erro: '{path}' não é um diretório."
        depth = max(1, min(depth or 2, 5))  # clamp 1-5
        lines: list[str] = [f"📁 {root.resolve()}"]
        self._walk_dir(root, lines, prefix="", current=0, max_depth=depth, show_hidden=show_hidden)
        return "\n".join(lines)

    def _walk_dir(
        self,
        directory: Path,
        lines: list[str],
        prefix: str,
        current: int,
        max_depth: int,
        show_hidden: bool,
    ) -> None:
        if current >= max_depth:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        except PermissionError:
            lines.append(f"{prefix}  [sem permissão]")
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
                size_str = f"{size:,}b" if size < 1024 else f"{size/1024:.1f}KB" if size < 1_048_576 else f"{size/1_048_576:.1f}MB"
                lines.append(f"{prefix}{connector}{entry.name}  [{size_str}]")

    def _search_text(
        self,
        pattern: str,
        directory: str,
        file_glob: str,
        literal: bool,
        max_results: int,
    ) -> str:
        if not pattern:
            return "Erro: pattern não informado."
        root = Path(directory)
        if not root.exists():
            return f"Erro: diretório '{directory}' não encontrado."

        max_results = max(1, min(max_results or 50, 500))
        glob = file_glob or "*"

        try:
            regex = re.compile(re.escape(pattern) if literal else pattern, re.IGNORECASE)
        except re.error as e:
            return f"Erro: regex inválida — {e}"

        results: list[str] = []
        files_searched = 0

        for file_path in sorted(root.rglob(glob)):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() in _BINARY_EXTS:
                continue
            # Pula arquivo muito grande para busca
            if file_path.stat().st_size > MAX_FILE_BYTES * 2:
                continue
            try:
                for lineno, line in enumerate(
                    file_path.read_text(encoding="utf-8", errors="replace").splitlines(),
                    start=1,
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
            return f"Nenhum resultado para '{pattern}' em {files_searched} arquivo(s)."

        header = f"🔍 {len(results)} resultado(s) para '{pattern}' [{files_searched} arquivo(s) pesquisados]:\n"
        suffix = f"\n… (limite de {max_results} atingido)" if len(results) == max_results else ""
        return header + "\n".join(results) + suffix

    def _shell_execute(self, command: str) -> str:
        # Rejeita imediatamente qualquer chamada sem comando — evita subprocess pendurado
        if not command or not command.strip():
            return (
                "❌ shell_execute bloqueado: parâmetro 'command' está VAZIO ou ausente.\n"
                "   Causa provável: a IA enviou a chamada antes de definir o comando.\n"
                "   SOLUÇÃO: reenvie a chamada com o campo 'command' preenchido.\n"
                "   Exemplo: shell_execute(command='ls -la')"
            )
        command = command.strip()
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=SHELL_TIMEOUT,
            )
            output = (result.stdout or "") + (result.stderr or "")
            if not output:
                return f"✅ Comando executado (exit {result.returncode}, sem saída)."
            # Trunca saídas massivas para não poluir o contexto
            if len(output) > 8_000:
                output = output[:8_000] + f"\n… [saída truncada — {len(output):,} chars total]"
            return output
        except subprocess.TimeoutExpired:
            return f"❌ Timeout: comando excedeu {SHELL_TIMEOUT}s."
        except OSError as e:
            return f"❌ Erro no shell: {e}"
