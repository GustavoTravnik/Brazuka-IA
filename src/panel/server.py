#!/usr/bin/env python3
"""
COIA Panel - Servidor Flask para gerenciar skills, crews, commands, prompts, sprints e execuções.
"""
import os
import sys
import glob
import json
import uuid
import yaml
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional
from flask import Flask, jsonify, request, send_from_directory, abort
from flask_cors import CORS

# Garante que o diretório raiz do projeto está no path para imports
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from services.daemon_client import daemon as _daemon
from services import cron_scheduler as _cron

PANEL_DIR       = os.path.dirname(os.path.abspath(__file__))
BASE_DIR        = os.path.dirname(PANEL_DIR)
STATIC_DIR      = os.path.join(PANEL_DIR, "static")
SKILLS_DIR      = os.path.join(BASE_DIR, "skills")
CREWS_DIR       = os.path.join(BASE_DIR, "crews")
COMMANDS_DIR    = os.path.join(BASE_DIR, "commands")
PROMPTS_DIR     = os.path.join(BASE_DIR, "prompts")
SPRINTS_DIR     = os.path.join(BASE_DIR, "sprints")
EXECUTIONS_DIR  = os.path.join(BASE_DIR, "executions")
MCP_SERVERS_DIR = os.path.join(BASE_DIR, "mcp-servers")
CRONS_DIR       = os.path.join(BASE_DIR, "crons")

app = Flask(__name__, static_folder=STATIC_DIR)
CORS(app)

# Garante que os diretórios existam independentemente do modo de inicialização
os.makedirs(EXECUTIONS_DIR, exist_ok=True)
os.makedirs(CRONS_DIR, exist_ok=True)

# Inicia o scheduler de crons em background (thread daemon)
_cron.start(_daemon)

# ─────────────────────────────────────────────
# STATIC
# ─────────────────────────────────────────────
@app.route("/")
def index():
    path = os.path.join(STATIC_DIR, "index.html")
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    # Injeta timestamp no lugar de __BUILD__ para forçar revalidação de assets a cada deploy
    build_ts = str(int(os.path.getmtime(path)))
    html = html.replace("__BUILD__", build_ts)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)

# ─────────────────────────────────────────────
# SKILLS
# ─────────────────────────────────────────────
def _extract_skill_description(path: str) -> str:
    """Extrai a primeira linha de conteúdo útil do .md como descrição curta da skill."""
    import re
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Remove padrão **Rótulo:** e variações antes de qualquer lstrip
                line = re.sub(r"\*\*[^*]+:\*\*\s*", "", line)
                line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
                line = re.sub(r"\*([^*]+)\*", r"\1", line)
                line = re.sub(r"`([^`]+)`", r"\1", line)
                line = line.lstrip("-*>: ").strip()
                if line:
                    return line[:120]
    except Exception:
        pass
    return ""

@app.route("/api/skills", methods=["GET"])
def list_skills():
    files = glob.glob(os.path.join(SKILLS_DIR, "*.md"))
    skills = []
    for f in sorted(files):
        name = os.path.splitext(os.path.basename(f))[0]
        skills.append({"name": name, "description": _extract_skill_description(f)})
    return jsonify(skills)

@app.route("/api/skills/<name>", methods=["GET"])
def get_skill(name):
    path = os.path.join(SKILLS_DIR, f"{name}.md")
    if not os.path.exists(path):
        abort(404)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return jsonify({"name": name, "content": content})

@app.route("/api/skills/<name>", methods=["PUT"])
def update_skill(name):
    data = request.get_json()
    content = data.get("content", "")
    path = os.path.join(SKILLS_DIR, f"{name}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return jsonify({"ok": True})

@app.route("/api/skills", methods=["POST"])
def create_skill():
    data = request.get_json()
    name = data.get("name", "").strip().replace(" ", "-")
    content = data.get("content", "")
    if not name:
        return jsonify({"error": "Nome obrigatório"}), 400
    path = os.path.join(SKILLS_DIR, f"{name}.md")
    if os.path.exists(path):
        return jsonify({"error": "Skill já existe"}), 409
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return jsonify({"ok": True, "name": name}), 201

@app.route("/api/skills/<name>", methods=["DELETE"])
def delete_skill(name):
    path = os.path.join(SKILLS_DIR, f"{name}.md")
    if not os.path.exists(path):
        abort(404)
    os.remove(path)
    return jsonify({"ok": True})

# ─────────────────────────────────────────────
# TOOLS (leitura dos mcp-servers disponíveis)
# ─────────────────────────────────────────────
@app.route("/api/tools", methods=["GET"])
def list_tools():
    """Retorna tools nativas + nomes dos mcp-servers disponíveis."""
    native = [
        "shell_execute",
        "read_files",
        "write_file",
        "patch_file",
        "list_dir",
        "search_text",
    ]

    mcp_files = glob.glob(os.path.join(MCP_SERVERS_DIR, "*.py"))
    mcp_tools = [os.path.splitext(os.path.basename(f))[0] for f in sorted(mcp_files)
                 if not os.path.basename(f).startswith("_")]

    return jsonify({"native": native, "mcp": mcp_tools})

# ─────────────────────────────────────────────
# MCPs CRUD
# ─────────────────────────────────────────────
def _mcp_requires_key(path: str) -> bool:
    """Retorna True se o arquivo contém '# REQUER CHAVE: Sim'."""
    import re
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if re.match(r"#\s*REQUER CHAVE\s*:\s*Sim", line.strip(), re.IGNORECASE):
                    return True
    except Exception:
        pass
    return False

def _extract_mcp_description(path: str) -> str:
    """Extrai o bloco de comentário '# O QUE FAZ: ...' do arquivo .py do MCP.
    Concatena todas as linhas do bloco até encontrar uma linha vazia ou não-comentário.
    Fallback: primeira linha de comentário útil encontrada no arquivo.
    """
    import re
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Procura pelo marcador "O QUE FAZ:" dentro de linhas de comentário
        in_block = False
        parts: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not in_block:
                # Detecta início do bloco — comentário contendo "O QUE FAZ:"
                if re.match(r"#\s*O QUE FAZ\s*:", stripped, re.IGNORECASE):
                    text = re.sub(r"^#\s*O QUE FAZ\s*:\s*", "", stripped, flags=re.IGNORECASE)
                    if text:
                        parts.append(text)
                    in_block = True
            else:
                # Continua acumulando linhas de comentário do bloco
                if stripped.startswith("#") and not re.match(r"#\s*REQUER CHAVE\s*:", stripped, re.IGNORECASE):
                    text = stripped.lstrip("#").strip()
                    if text:
                        parts.append(text)
                else:
                    # Linha vazia, não-comentário ou "REQUER CHAVE:" encerra o bloco
                    break

        if parts:
            return " ".join(parts)[:200]

        # Fallback: primeira linha de comentário não vazia
        for line in lines:
            text = line.strip().lstrip("#").strip()
            if text and not line.strip().startswith("import"):
                return text[:200]
    except Exception:
        pass
    return ""

@app.route("/api/mcps", methods=["GET"])
def list_mcps():
    files = glob.glob(os.path.join(MCP_SERVERS_DIR, "*.py"))
    mcps = []
    for f in sorted(files):
        if os.path.basename(f).startswith("_"):
            continue
        name = os.path.splitext(os.path.basename(f))[0]
        mcps.append({
            "name": name,
            "description": _extract_mcp_description(f),
            "requires_key": _mcp_requires_key(f),
        })
    return jsonify(mcps)

@app.route("/api/mcps/<name>", methods=["GET"])
def get_mcp(name):
    path = os.path.join(MCP_SERVERS_DIR, f"{name}.py")
    if not os.path.exists(path):
        abort(404)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return jsonify({"name": name, "content": content})

@app.route("/api/mcps/<name>", methods=["PUT"])
def update_mcp(name):
    data = request.get_json()
    content = data.get("content", "")
    path = os.path.join(MCP_SERVERS_DIR, f"{name}.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return jsonify({"ok": True})

@app.route("/api/mcps", methods=["POST"])
def create_mcp():
    data = request.get_json()
    name = data.get("name", "").strip().replace(" ", "-")
    content = data.get("content", "")
    if not name:
        return jsonify({"error": "Nome obrigatório"}), 400
    path = os.path.join(MCP_SERVERS_DIR, f"{name}.py")
    if os.path.exists(path):
        return jsonify({"error": "MCP já existe"}), 409
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return jsonify({"ok": True, "name": name}), 201

@app.route("/api/mcps/<name>", methods=["DELETE"])
def delete_mcp(name):
    path = os.path.join(MCP_SERVERS_DIR, f"{name}.py")
    if not os.path.exists(path):
        abort(404)
    os.remove(path)
    return jsonify({"ok": True})

# ─────────────────────────────────────────────
# CREWS
# ─────────────────────────────────────────────
@app.route("/api/crews", methods=["GET"])
def list_crews():
    files = glob.glob(os.path.join(CREWS_DIR, "*.yaml"))
    crews = []
    for f in sorted(files):
        name = os.path.splitext(os.path.basename(f))[0]
        with open(f, "r", encoding="utf-8") as fp:
            data = yaml.safe_load(fp) or {}
        crews.append({
            "name": name,
            "title": data.get("title", ""),
            "description": data.get("description", ""),
            "agents_count": len(data.get("crew", [])),
        })
    return jsonify(crews)

@app.route("/api/crews/<name>", methods=["GET"])
def get_crew(name):
    path = os.path.join(CREWS_DIR, f"{name}.yaml")
    if not os.path.exists(path):
        abort(404)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return jsonify({"name": name, "data": data})

@app.route("/api/crews/<name>", methods=["PUT"])
def update_crew(name):
    body = request.get_json()
    title = body.get("title", "")
    description = body.get("description", "")
    agents = body.get("data", {}).get("crew", [])
    path = os.path.join(CREWS_DIR, f"{name}.yaml")
    data = {"title": title, "description": description, "crew": agents}
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return jsonify({"ok": True})

@app.route("/api/crews", methods=["POST"])
def create_crew():
    body = request.get_json()
    name = body.get("name", "").strip().replace(" ", "-")
    title = body.get("title", "")
    description = body.get("description", "")
    agents = body.get("data", {}).get("crew", [])
    if not name:
        return jsonify({"error": "Nome obrigatório"}), 400
    path = os.path.join(CREWS_DIR, f"{name}.yaml")
    if os.path.exists(path):
        return jsonify({"error": "Crew já existe"}), 409
    data = {"title": title, "description": description, "crew": agents}
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return jsonify({"ok": True, "name": name}), 201

@app.route("/api/crews/<name>", methods=["DELETE"])
def delete_crew(name):
    path = os.path.join(CREWS_DIR, f"{name}.yaml")
    if not os.path.exists(path):
        abort(404)
    os.remove(path)
    return jsonify({"ok": True})

# ─────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────
@app.route("/api/commands", methods=["GET"])
def list_commands():
    files = glob.glob(os.path.join(COMMANDS_DIR, "*.md"))
    cmds = [os.path.splitext(os.path.basename(f))[0] for f in sorted(files)]
    return jsonify(cmds)

@app.route("/api/commands/<name>", methods=["GET"])
def get_command(name):
    path = os.path.join(COMMANDS_DIR, f"{name}.md")
    if not os.path.exists(path):
        abort(404)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return jsonify({"name": name, "content": content})

@app.route("/api/commands/<name>", methods=["PUT"])
def update_command(name):
    data = request.get_json()
    content = data.get("content", "")
    path = os.path.join(COMMANDS_DIR, f"{name}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return jsonify({"ok": True})

@app.route("/api/commands", methods=["POST"])
def create_command():
    data = request.get_json()
    name = data.get("name", "").strip().replace(" ", "-")
    content = data.get("content", "")
    if not name:
        return jsonify({"error": "Nome obrigatório"}), 400
    path = os.path.join(COMMANDS_DIR, f"{name}.md")
    if os.path.exists(path):
        return jsonify({"error": "Command já existe"}), 409
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return jsonify({"ok": True, "name": name}), 201

@app.route("/api/commands/<name>", methods=["DELETE"])
def delete_command(name):
    path = os.path.join(COMMANDS_DIR, f"{name}.md")
    if not os.path.exists(path):
        abort(404)
    os.remove(path)
    return jsonify({"ok": True})

# ─────────────────────────────────────────────
# PROMPTS
# ─────────────────────────────────────────────
@app.route("/api/prompts", methods=["GET"])
def list_prompts():
    files = glob.glob(os.path.join(PROMPTS_DIR, "*.md"))
    prompts = [os.path.splitext(os.path.basename(f))[0] for f in sorted(files)]
    return jsonify(prompts)

@app.route("/api/prompts/<name>", methods=["GET"])
def get_prompt(name):
    path = os.path.join(PROMPTS_DIR, f"{name}.md")
    if not os.path.exists(path):
        abort(404)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return jsonify({"name": name, "content": content})

@app.route("/api/prompts/<name>", methods=["PUT"])
def update_prompt(name):
    data = request.get_json()
    content = data.get("content", "")
    path = os.path.join(PROMPTS_DIR, f"{name}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return jsonify({"ok": True})

@app.route("/api/prompts", methods=["POST"])
def create_prompt():
    data = request.get_json()
    name = data.get("name", "").strip().replace(" ", "-")
    content = data.get("content", "")
    if not name:
        return jsonify({"error": "Nome obrigatório"}), 400
    path = os.path.join(PROMPTS_DIR, f"{name}.md")
    if os.path.exists(path):
        return jsonify({"error": "Prompt já existe"}), 409
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return jsonify({"ok": True, "name": name}), 201

@app.route("/api/prompts/<name>", methods=["DELETE"])
def delete_prompt(name):
    path = os.path.join(PROMPTS_DIR, f"{name}.md")
    if not os.path.exists(path):
        abort(404)
    os.remove(path)
    return jsonify({"ok": True})

# ─────────────────────────────────────────────
# SPRINTS
# ─────────────────────────────────────────────
@app.route("/api/sprints", methods=["GET"])
def list_sprints():
    files = glob.glob(os.path.join(SPRINTS_DIR, "*.yaml"))
    sprints = []
    for f in sorted(files):
        name = os.path.splitext(os.path.basename(f))[0]
        with open(f, "r", encoding="utf-8") as fp:
            data = yaml.safe_load(fp) or {}
        raw_tasks = [t for t in (data.get("tasks") or []) if isinstance(t, dict)]
        sprints.append({
            "name": name,
            "title": data.get("title", name),
            "status": data.get("status", "open"),
            "tasks_count": len(raw_tasks),
            "tasks": [{"status": t.get("status", "open")} for t in raw_tasks],
            "created_at": data.get("created_at", ""),
        })
    return jsonify(sprints)

@app.route("/api/sprints/<name>", methods=["GET"])
def get_sprint(name):
    path = os.path.join(SPRINTS_DIR, f"{name}.yaml")
    if not os.path.exists(path):
        abort(404)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return jsonify({"name": name, "data": data})

@app.route("/api/sprints/<name>", methods=["PUT"])
def update_sprint(name):
    body = request.get_json()
    data = body.get("data", {})
    path = os.path.join(SPRINTS_DIR, f"{name}.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return jsonify({"ok": True})

@app.route("/api/sprints", methods=["POST"])
def create_sprint():
    body = request.get_json()
    name = body.get("name", "").strip().replace(" ", "-")
    title = body.get("title", name)
    description = body.get("description", "")
    tasks = body.get("tasks", [])
    updates = body.get("updates", [])
    status = body.get("status", "open")
    if status not in ("open", "in_progress", "done"):
        status = "open"
    if not name:
        return jsonify({"error": "Nome obrigatório"}), 400
    path = os.path.join(SPRINTS_DIR, f"{name}.yaml")
    if os.path.exists(path):
        return jsonify({"error": "Sprint já existe"}), 409
    # Garante que cada tarefa tenha os campos padrão
    for task in tasks:
        if isinstance(task, dict):
            task.setdefault("updates", [])
            task_status = task.get("status", "open")
            if task_status not in ("open", "in_progress", "done"):
                task_status = "open"
            task["status"] = task_status
    data = {
        "title": title,
        "name": name,
        "description": description,
        "status": status,
        "created_at": datetime.now().isoformat(),
        "tasks": tasks,
        "updates": updates,
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return jsonify({"ok": True, "name": name}), 201

@app.route("/api/sprints/<name>", methods=["DELETE"])
def delete_sprint(name):
    path = os.path.join(SPRINTS_DIR, f"{name}.yaml")
    if not os.path.exists(path):
        abort(404)
    os.remove(path)
    return jsonify({"ok": True})

# ─────────────────────────────────────────────
# EXECUÇÕES DE SPRINTS
# ─────────────────────────────────────────────
def _exec_path(exec_id: str) -> str:
    return os.path.join(EXECUTIONS_DIR, f"{exec_id}.json")

def _load_execution(exec_id: str) -> dict | None:
    path = _exec_path(exec_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_execution(data: dict) -> None:
    path = _exec_path(data["id"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _reconcile_execution_status(data: dict) -> dict:
    """
    Se o .json diz 'running' mas o .daemon.json diz outra coisa (crashed, success,
    error, stopped), sincroniza o .json com a verdade do daemon.

    Isso corrige o caso de reboot: o processo morreu, o daemon reconciliou o
    .daemon.json para 'crashed', mas o .json ainda diz 'running'.
    """
    if data.get("status") != "running":
        return data  # já tem status final — nada a reconciliar

    exec_id    = data["id"]
    daemon_path = Path(EXECUTIONS_DIR) / f"{exec_id}.daemon.json"
    if not daemon_path.exists():
        return data

    try:
        daemon_state = json.loads(daemon_path.read_text(encoding="utf-8"))
    except Exception:
        return data

    daemon_status = daemon_state.get("status", "")
    # Qualquer status final no daemon.json corrige o .json
    if daemon_status in ("crashed", "success", "error", "stopped"):
        data["status"]      = daemon_status
        data["finished_at"] = daemon_state.get("finished_at", datetime.now().isoformat())
        _save_execution(data)

    return data

@app.route("/api/executions", methods=["GET"])
def list_executions():
    files = glob.glob(os.path.join(EXECUTIONS_DIR, "[!.]*.json"))
    files = [f for f in files if not any(x in f for x in (".checkpoint.", ".daemon."))]
    execs = []
    for f in sorted(files, reverse=True):
        with open(f, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        data = _reconcile_execution_status(data)  # corrige fantasmas de reboot
        execs.append({
            "id": data["id"],
            "sprint": data.get("sprint"),
            "crew": data.get("crew"),
            "status": data.get("status", "idle"),
            "created_at": data.get("created_at", ""),
            "started_at": data.get("started_at", ""),
            "finished_at": data.get("finished_at", ""),
            "title": data.get("title", ""),
        })
    return jsonify(execs)

@app.route("/api/executions/<exec_id>", methods=["GET"])
def get_execution(exec_id):
    data = _load_execution(exec_id)
    if not data:
        abort(404)
    data = _reconcile_execution_status(data)  # corrige fantasmas de reboot
    return jsonify(data)

@app.route("/api/executions", methods=["POST"])
def create_execution():
    body = request.get_json()
    sprint_name = body.get("sprint", "")
    crew_name = body.get("crew", "")
    title = body.get("title", f"{sprint_name} × {crew_name}")
    if not sprint_name or not crew_name:
        return jsonify({"error": "Sprint e Crew são obrigatórios"}), 400

    exec_id = str(uuid.uuid4())[:8]
    data = {
        "id": exec_id,
        "sprint": sprint_name,
        "crew": crew_name,
        "title": title,
        "status": "idle",
        "created_at": datetime.now().isoformat(),
        "started_at": "",
        "finished_at": "",
    }
    _save_execution(data)
    return jsonify({"ok": True, "id": exec_id}), 201

@app.route("/api/executions/<exec_id>", methods=["DELETE"])
def delete_execution(exec_id):
    path = _exec_path(exec_id)
    if not os.path.exists(path):
        abort(404)
    os.remove(path)
    # Remove também o .log e .daemon.json do daemon se existirem
    for ext in (".log", ".daemon.json"):
        p = Path(EXECUTIONS_DIR) / f"{exec_id}{ext}"
        if p.exists():
            p.unlink(missing_ok=True)
    return jsonify({"ok": True})

@app.route("/api/executions/<exec_id>/start", methods=["POST"])
def start_execution(exec_id):
    """Delega a execução ao daemon — processo independente que sobrevive ao painel."""
    data = _load_execution(exec_id)
    if not data:
        abort(404)

    sprint_name = data["sprint"]
    crew_name   = data["crew"]
    sprint_path = os.path.join(SPRINTS_DIR, f"{sprint_name}.yaml")
    if not os.path.exists(sprint_path):
        return jsonify({"error": f"Sprint '{sprint_name}' não encontrada"}), 404

    app_path = os.path.join(BASE_DIR, "app.py")
    cmd = [sys.executable, "-u", app_path, "--crew", crew_name, "--sprint", sprint_path]

    try:
        result = _daemon.start(exec_id=exec_id, cmd=cmd, cwd=BASE_DIR)
    except Exception as e:
        return jsonify({"error": f"Daemon indisponível: {e}"}), 503

    if "error" in result:
        return jsonify(result), 409

    data["status"]      = "running"
    data["started_at"]  = datetime.now().isoformat()
    data["finished_at"] = ""
    data["logs"]        = []
    _save_execution(data)
    return jsonify({"ok": True, "message": f"Execução {exec_id} iniciada via daemon"})


@app.route("/api/executions/<exec_id>/stop", methods=["POST"])
def stop_execution(exec_id):
    """Para a execução via daemon."""
    try:
        _daemon.stop(exec_id)
    except Exception:
        pass
    data = _load_execution(exec_id)
    if data:
        data["status"]      = "stopped"
        data["finished_at"] = datetime.now().isoformat()
        _save_execution(data)
    return jsonify({"ok": True})


@app.route("/api/executions/<exec_id>/input", methods=["POST"])
def send_input(exec_id):
    """Envia texto ao stdin do processo via daemon."""
    body = request.get_json(silent=True) or {}
    text = body.get("text", "").strip()
    if text not in ("y", "n", "Y", "N", "yes", "no", ""):
        return jsonify({"error": "Valor inválido — use y ou n"}), 400
    try:
        result = _daemon.send_stdin(exec_id, text)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/executions/<exec_id>/logs", methods=["GET"])
def get_execution_logs(exec_id):
    """Retorna logs + status via daemon (processo vivo) ou disco (processo encerrado)."""
    since = request.args.get("since", 0, type=int)
    try:
        result = _daemon.logs(exec_id=exec_id, since=since)
        status = result.get("status", "unknown")
        logs   = result.get("logs", [])
        total  = result.get("total", since + len(logs))
    except Exception:
        # Daemon indisponível — lê direto do arquivo .log em disco
        log_path = Path(EXECUTIONS_DIR) / f"{exec_id}.log"
        all_logs = []
        if log_path.exists():
            all_logs = [l.rstrip() for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        logs   = all_logs[since:]
        total  = len(all_logs)
        status = (_load_execution(exec_id) or {}).get("status", "unknown")

    # Sincroniza status no JSON se o processo terminou
    exec_data = _load_execution(exec_id) or {}
    if status in ("success", "error", "stopped") and exec_data.get("status") == "running":
        exec_data["status"]      = status
        exec_data["finished_at"] = datetime.now().isoformat()
        _save_execution(exec_data)
        exec_data = _load_execution(exec_id) or exec_data

    return jsonify({
        "logs":        logs,
        "total":       total,
        "status":      exec_data.get("status", status),
        "started_at":  exec_data.get("started_at", ""),
        "finished_at": exec_data.get("finished_at", ""),
    })

# ─────────────────────────────────────────────
# CRONS CRUD
# ─────────────────────────────────────────────
_CRON_DEFAULTS = {
    "enabled": True,
    "model":   "gemini-2.5-flash",
    "skills":  [],
    "mcps":    None,
    "prompt":  "",
}

def _cron_path(name: str) -> str:
    return os.path.join(CRONS_DIR, f"{name}.yaml")

def _load_cron(name: str) -> dict | None:
    path = _cron_path(name)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _save_cron(name: str, data: dict) -> None:
    with open(_cron_path(name), "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

@app.route("/api/crons", methods=["GET"])
def list_crons():
    files = glob.glob(os.path.join(CRONS_DIR, "*.yaml"))
    crons = []
    for f in sorted(files):
        name = os.path.splitext(os.path.basename(f))[0]
        data = yaml.safe_load(open(f, encoding="utf-8")) or {}
        crons.append({
            "name":       name,
            "expression": data.get("expression", ""),
            "prompt":     data.get("prompt", ""),
            "model":      data.get("model", _CRON_DEFAULTS["model"]),
            "skills":     data.get("skills", []),
            "mcps":       data.get("mcps", None),
            "enabled":    data.get("enabled", True),
        })
    return jsonify(crons)

@app.route("/api/crons/<name>", methods=["GET"])
def get_cron(name):
    data = _load_cron(name)
    if data is None:
        abort(404)
    return jsonify({"name": name, **data})

@app.route("/api/crons", methods=["POST"])
def create_cron():
    body = request.get_json()
    name = body.get("name", "").strip().replace(" ", "-")
    if not name:
        return jsonify({"error": "Nome obrigatório"}), 400
    if os.path.exists(_cron_path(name)):
        return jsonify({"error": "Cron já existe"}), 409
    data = {
        "name":       name,
        "expression": body.get("expression", "0 9 * * 1-5"),
        "prompt":     body.get("prompt", ""),
        "model":      body.get("model", _CRON_DEFAULTS["model"]),
        "skills":     body.get("skills", []),
        "mcps":       body.get("mcps", None),
        "enabled":    body.get("enabled", True),
    }
    _save_cron(name, data)
    return jsonify({"ok": True, "name": name}), 201

@app.route("/api/crons/<name>", methods=["PUT"])
def update_cron(name):
    if not os.path.exists(_cron_path(name)):
        abort(404)
    body = request.get_json()
    data = {
        "name":       name,
        "expression": body.get("expression", "0 9 * * 1-5"),
        "prompt":     body.get("prompt", ""),
        "model":      body.get("model", _CRON_DEFAULTS["model"]),
        "skills":     body.get("skills", []),
        "mcps":       body.get("mcps", None),
        "enabled":    body.get("enabled", True),
    }
    _save_cron(name, data)
    return jsonify({"ok": True})

@app.route("/api/crons/<name>", methods=["DELETE"])
def delete_cron(name):
    path = _cron_path(name)
    if not os.path.exists(path):
        abort(404)
    os.remove(path)
    return jsonify({"ok": True})

@app.route("/api/crons/<name>/toggle", methods=["POST"])
def toggle_cron(name):
    data = _load_cron(name)
    if data is None:
        abort(404)
    data["enabled"] = not data.get("enabled", True)
    _save_cron(name, data)
    return jsonify({"ok": True, "enabled": data["enabled"]})

@app.route("/api/crons/<name>/fire", methods=["POST"])
def fire_cron(name):
    """Dispara a cron imediatamente (teste manual)."""
    data = _load_cron(name)
    if data is None:
        abort(404)
    try:
        _cron._fire(name, data)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/crons/scheduler/status", methods=["GET"])
def cron_scheduler_status():
    return jsonify(_cron.status())

@app.route("/api/crons/preview", methods=["POST"])
def cron_preview():
    """Retorna as próximas execuções de uma expressão cron."""
    body = request.get_json()
    expression = body.get("expression", "")
    runs = _cron.next_runs(expression, count=5)
    return jsonify({"next_runs": runs})

# ─────────────────────────────────────────────
# SESSÃO INTERATIVA
# ─────────────────────────────────────────────
@app.route("/api/session/start", methods=["POST"])
def start_session():
    """
    Abre um terminal do sistema executando exatamente o comando recebido.
    O comando vem do textbox #cmdline do painel (ex: coia --skills "[rtk-gain]").
    Usa bash -i para carregar o .bashrc e resolver o alias 'coia'.
    """
    body = request.get_json(silent=True) or {}
    cmd  = body.get("cmd", "").strip()
    if not cmd:
        return jsonify({"error": "Comando vazio"}), 400

    try:
        subprocess.Popen(
            [
                "gnome-terminal", "--",
                "bash", "-i", "-c",
                f'{cmd}; _rc=$?; echo ""; if [ $_rc -ne 0 ]; then echo "── erro (exit $_rc) — pressione qualquer tecla para fechar ──"; else echo "── sessão encerrada ──"; fi; read -n1',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return jsonify({"ok": True, "cmd": cmd})
    except FileNotFoundError:
        return jsonify({"error": "gnome-terminal não encontrado no sistema"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# SESSÃO SKILL BUILDER
# ─────────────────────────────────────────────
@app.route("/api/session/start-skill-builder", methods=["POST"])
def start_skill_builder_session():
    """
    Abre um terminal focado em criar skills para o COIA.
    Carrega apenas a skill skill-builder + clean-code + zero-filler.
    Usa --no-mcp para não carregar ferramentas desnecessárias.
    Exibe dicas no console antes de iniciar o agente.
    """
    skills = ["skill-builder", "agent-performance", "clean-code", "zero-filler", "install-on-demand"]
    skills_arg = f'--skills "[{",".join(skills)}]"'

    skills_dir = SKILLS_DIR
    existing_skills = sorted([
        os.path.splitext(os.path.basename(f))[0]
        for f in glob.glob(os.path.join(skills_dir, "*.md"))
    ])
    skills_list_str = "\\n".join(f"  • {s}" for s in existing_skills)

    dicas = (
        "╔══════════════════════════════════════════════════════════╗\\n"
        "║           🧠  COIA — CRIADOR DE SKILLS                  ║\\n"
        "╚══════════════════════════════════════════════════════════╝\\n"
        "\\n"
        "  Este terminal foi aberto para criar uma nova skill.\\n"
        "  O agente já carregou as instruções de como criar skills\\n"
        "  de qualidade e vai te guiar pelo processo.\\n"
        "\\n"
        "  💡 DICAS PARA UM BOM RESULTADO:\\n"
        "\\n"
        "  1. Seja ESPECÍFICO sobre o que a skill deve fazer\\n"
        "     Ex: 'skill para gerar Dockerfiles de produção para Node.js'\\n"
        "     Não: 'skill de Docker'\\n"
        "\\n"
        "  2. Diga QUANDO o agente deve usar o conhecimento\\n"
        "     Ex: 'sempre que criar ou revisar um Dockerfile'\\n"
        "\\n"
        "  3. Mencione ANTIPADRÕES que o agente deve evitar\\n"
        "     Ex: 'nunca usar a tag latest, sempre definir HEALTHCHECK'\\n"
        "\\n"
        "  4. Se tiver exemplos reais de código, compartilhe\\n"
        "     O agente vai extrair os padrões automaticamente\\n"
        "\\n"
        f"  📋 SKILLS JÁ EXISTENTES ({len(existing_skills)} skills):\\n"
        f"{skills_list_str}\\n"
        "\\n"
        "  ─────────────────────────────────────────────────────────\\n"
        "  Descreva a skill que você quer criar para o COIA:↓\\n"
        "  ─────────────────────────────────────────────────────────\\n"
        "\\n"
    )

    cmd = f'echo -e "{dicas}" && coia {skills_arg} --no-mcp --no-clear'

    try:
        subprocess.Popen(
            [
                "gnome-terminal", "--",
                "bash", "-i", "-c",
                f'{cmd}; _rc=$?; echo ""; if [ $_rc -ne 0 ]; then echo "── erro (exit $_rc) — pressione qualquer tecla para fechar ──"; else echo "── sessão encerrada ──"; fi; read -n1',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return jsonify({"ok": True, "skills": skills})
    except FileNotFoundError:
        return jsonify({"error": "gnome-terminal não encontrado no sistema"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# SESSÃO CREW BUILDER
# ─────────────────────────────────────────────
@app.route("/api/session/start-crew-builder", methods=["POST"])
def start_crew_builder_session():
    """
    Abre um terminal focado em criar uma crew YAML completa para o COIA.
    Recebe tipo, nome, objetivo e stack do usuário e monta um prompt rico
    com contexto das crews existentes para que o agente gere a crew ideal.
    """
    body = request.get_json(silent=True) or {}
    crew_name  = body.get("name", "").strip().replace(" ", "-")
    crew_type  = body.get("type", "").strip()
    objective  = body.get("objective", "").strip()
    stack      = body.get("stack", "").strip()

    if not crew_name:
        return jsonify({"error": "Nome da crew é obrigatório"}), 400
    if not crew_type and not objective:
        return jsonify({"error": "Selecione um tipo ou descreva o objetivo"}), 400

    # Verifica se já existe
    crew_path = os.path.join(CREWS_DIR, f"{crew_name}.yaml")
    if os.path.exists(crew_path):
        return jsonify({"error": f"Crew '{crew_name}' já existe. Escolha outro nome."}), 409

    # Coleta nomes das crews existentes e resumos para contexto
    crew_files = glob.glob(os.path.join(CREWS_DIR, "*.yaml"))
    crew_summaries = []
    for f in sorted(crew_files):
        fname = os.path.splitext(os.path.basename(f))[0]
        with open(f, "r", encoding="utf-8") as fp:
            data = yaml.safe_load(fp) or {}
        desc = (data.get("description") or "")[:200]
        agents = data.get("crew", [])
        agent_names = [a.get("name", "?") for a in agents if isinstance(a, dict)]
        crew_summaries.append(
            f"- **{fname}**: {desc.strip()}\n"
            f"  Agentes: {', '.join(agent_names)}"
        )
    crew_context = "\n".join(crew_summaries) if crew_summaries else "(nenhuma crew existente)"

    # Coleta skills disponíveis
    skill_files = glob.glob(os.path.join(SKILLS_DIR, "*.md"))
    available_skills = sorted([
        os.path.splitext(os.path.basename(f))[0] for f in skill_files
    ])

    # Coleta MCPs disponíveis
    mcp_files = glob.glob(os.path.join(MCP_SERVERS_DIR, "*.py"))
    available_mcps = sorted([
        os.path.splitext(os.path.basename(f))[0]
        for f in mcp_files if not os.path.basename(f).startswith("_")
    ])

    # Mapeamento de tipo para descrição detalhada
    type_descriptions = {
        "bug-resolution": "Resolução de bugs — recebe um issue/bug report, investiga logs e código, identifica a causa raiz, aplica a correção e gera relatório",
        "dotnet-development": "Desenvolvimento de aplicação .NET/C# — APIs, serviços, processors",
        "nodejs-development": "Desenvolvimento Node.js/TypeScript — APIs REST, serviços, processadores assíncronos",
        "python-development": "Desenvolvimento Python — scripts, APIs FastAPI/Flask, processamento de dados, ML",
        "java-development": "Desenvolvimento Java — APIs Spring Boot, microserviços, processamento",
        "mobile-flutter": "Desenvolvimento de aplicativo mobile com Flutter/Dart — com builds para iOS e Android",
        "mobile-native": "Desenvolvimento mobile nativo — apps separados para iOS (Swift) e Android (Kotlin)",
        "fullstack-web": "Desenvolvimento fullstack web — frontend (React/Vue/Angular) + backend + banco de dados",
        "api-backend": "Desenvolvimento de API/Backend — endpoints REST ou GraphQL, integrações, processadores de eventos",
        "infra-devops": "Infraestrutura e DevOps — CI/CD pipelines, IaC (CDKTF/Terraform), Docker, deploy em cloud (AWS/GCP)",
        "data-pipeline": "Pipeline de dados — ETL, Airflow DAGs, processamento batch/streaming, data lake",
        "migration": "Migração de sistema — reescrita de sistema legado para nova stack, preservando regras de negócio",
        "code-review": "Code review automatizado — análise de PRs, comentários de revisão, aplicação de fixes",
        "investigation": "Investigação e análise técnica — responder dúvidas sobre arquitetura, código e sistemas",
        "documentation": "Documentação técnica — gerar docs de API, arquitetura, fluxos, README",
        "testing": "Testes e QA — cobertura de testes unitários, integração, e2e",
        "custom": "Crew personalizada — tipo definido pelo usuário na descrição do objetivo",
    }
    type_desc = type_descriptions.get(crew_type, crew_type)

    # Monta o prompt completo para o agente
    context = f"""# Tarefa: Criar uma Crew COIA completa

## Dados fornecidos pelo usuário

- **Nome da crew (slug do arquivo):** {crew_name}
- **Tipo selecionado:** {type_desc}
- **Objetivo descrito pelo usuário:** {objective if objective else '(não informado — use o tipo como guia)'}
- **Stack/Tecnologias:** {stack if stack else '(não informado — infira do tipo)'}

## O que você deve fazer

Crie um arquivo YAML de crew completo em: {crew_path}

O arquivo deve seguir EXATAMENTE o formato das crews existentes do COIA.

## Estrutura obrigatória do YAML

```yaml
title: 'Título da Crew'
description: |
  Descrição detalhada do que a crew faz, quais agentes tem,
  e o fluxo de trabalho entre eles.

crew:
  - name: Nome do Agente
    modelId: gemini-2.5-flash
    clean_context_after_run: true
    persona: |
      Descrição detalhada da persona do agente...
    roles:
      - |
        Instrução detalhada 1...
      - |
        Instrução detalhada 2...
    output_flow: |
      Como o agente deve formatar sua saída...
    skills:
      - skill-name-1
      - skill-name-2
    tools:
      - shell_execute
      - read_files
    transitions:
      - condition: |
          Quando deve ir para outro agente...
        target: Nome do Agente Destino
      - condition: |
          Quando encerrar sem chamar ninguém...
        target: null
```

## Regras obrigatórias para criação da crew

### 1. SEMPRE tenha um Gerente/Orquestrador
- Use modelId `gemini-2.5-flash` (barato e rápido — ele só roteia)
- Persona: roteador operacional puro, NÃO executa código, NÃO cria tarefas
- Ele lê a sprint, identifica a próxima tarefa e delega ao agente correto
- Deve ter transitions claras para cada agente da crew
- O Gerente é SEMPRE o primeiro agente da lista (entry point)

### 2. SEMPRE tenha um Arquiteto/Planejador
- Use modelId `gemini-2.5-pro` (mais inteligente — planeja bem)
- NÃO escreve código, NÃO executa comandos — apenas PLANEJA e cria tarefas na sprint
- Lê o projeto fonte (se houver), analisa a especificação e cria tarefas [DEV] e [TEST]
- Cada tarefa deve ser atômica e autocontida com toda a informação necessária
- Usa SEMPRE patch_file para inserir tarefas na sprint (nunca write_file)
- Skill obrigatória: coia-task-manager

### 3. Tenha ao menos 1 agente Desenvolvedor
- Use modelId `gemini-2.5-flash` (bom equilíbrio custo/qualidade)
- Implementa exatamente o que está descrito na tarefa [DEV]
- Faz commit ao concluir cada tarefa (segue skill coia-task-manager)
- Se encontrar dúvida, encaminha de volta ao Gerente
- Se a crew envolve MÚLTIPLAS linguagens/plataformas, crie agentes devs SEPARADOS
  (ex: Dev Backend + Dev Frontend, ou Dev iOS + Dev Android)

### 4. Tenha um agente de QA/Testes
- Use modelId `gemini-2.5-flash` (testes são mais mecânicos)
- Implementa testes para as tarefas [TEST] criadas pelo Arquiteto
- NÃO modifica código de produção — se achar bug, reporta ao Gerente
- Faz commit dos testes

### 5. Opcionalmente, tenha um Code Janitor (limpeza pós-sprint)
- Use modelId `gemini-2.5-flash`
- Roda DEPOIS de todas as tarefas DEV e TEST estarem done
- Remove artefatos de build, comentários desnecessários, imports mortos
- Marca a sprint como done

### 6. Fluxo de transições (OBRIGATÓRIO seguir este padrão)
- Gerente recebe a sprint → se sprint está open, encaminha ao Arquiteto
- Arquiteto cria tarefas → volta ao Gerente
- Gerente delega [DEV] ao Dev → Dev conclui → volta ao Gerente
- Gerente delega [TEST] ao QA → QA conclui → volta ao Gerente
- Se QA acha bug → volta ao Gerente → Gerente redelega ao Dev
- Quando tudo done → Gerente encaminha ao Code Janitor (se houver)
- Code Janitor encerra a sprint
- Cada agente DEVE ter uma transition target: null para encerrar em caso de erro irrecuperável

### 7. Skills — distribua corretamente

Skills disponíveis no sistema:
{chr(10).join(f"- {s}" for s in available_skills)}

Diretrizes de atribuição:
- TODOS os agentes devem ter: agent-performance, coia-task-manager, clean-code
- Gerente: apenas coia-task-manager, clean-code, agent-performance
- Arquiteto: adicione as skills da stack relevante (dotnet, nodejs, python, mongodb, postgresql, etc.)
  e META-github-repos-map se precisar localizar repositórios
- Dev: adicione as skills da stack + install-on-demand
- QA: mesmas skills de stack do Dev
- Code Janitor: clean-code, coia-task-manager, agent-performance

### 8. Tools — distribua corretamente

Tools nativas disponíveis: shell_execute, read_files, write_file, patch_file, list_dir, search_text

MCP servers disponíveis (integrações externas): {', '.join(available_mcps) if available_mcps else '(nenhum)'}

Diretrizes:
- Gerente: apenas read_files, patch_file (ele só lê sprint e roteia)
- Arquiteto: shell_execute, read_files, list_dir, search_text, patch_file (lê código, cria tarefas)
- Dev: shell_execute, read_files, write_file, patch_file, list_dir, search_text (implementa tudo)
- QA: shell_execute, read_files, write_file, patch_file, list_dir, search_text
- Code Janitor: shell_execute, read_files, write_file, patch_file, list_dir, search_text
- Adicione MCPs relevantes:
  - jira: se a crew interage com issues Jira
  - bitbucket: se precisa ler/interagir com PRs ou repos Bitbucket
  - aws: se precisa acessar recursos AWS (CloudWatch, Lambda, etc.)
  - documentdb: se precisa acessar MongoDB/DocumentDB diretamente
  - slack: se precisa enviar notificações
  - brave-search / tavily: se precisa buscar informações na web

## Crews existentes como referência (use como modelo de qualidade)

{crew_context}

## Importante

- Gere o arquivo YAML completo e salve em: {crew_path}
- Use write_file para criar o arquivo
- Cada agente deve ter persona DETALHADA (mínimo 10 linhas) e específica para o domínio
- Cada role deve ser uma instrução longa e completa (mínimo 3 roles por agente)
- As transitions devem cobrir TODOS os cenários (sucesso, erro, dúvida, fim)
- O output_flow deve descrever o formato exato da saída de cada agente
- TODAS as personas devem ter restrições explícitas (o que o agente NÃO faz)
- Depois de criar o arquivo, informe ao usuário que a crew foi criada e mostre um resumo
"""

    # Skills que o agente builder vai usar
    skills = [
        "agent-performance",
        "clean-code",
        "coia-task-manager",
        "install-on-demand",
    ]
    skills_arg = f'--skills "[{",".join(skills)}]"'

    import tempfile
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    tmp.write(context)
    tmp.flush()
    tmp_path = tmp.name
    tmp.close()

    cmd = f'coia {skills_arg} --context-file {tmp_path} --no-clear'

    try:
        subprocess.Popen(
            [
                "gnome-terminal", "--",
                "bash", "-i", "-c",
                f'{cmd}; _rc=$?; echo ""; if [ $_rc -ne 0 ]; then echo "── erro (exit $_rc) — pressione qualquer tecla para fechar ──"; else echo "── sessão encerrada ──"; fi; read -n1',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return jsonify({"ok": True, "crew_name": crew_name, "skills": skills})
    except FileNotFoundError:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return jsonify({"error": "gnome-terminal não encontrado no sistema"}), 500
    except Exception as e:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# SESSÃO COM CONTEXTO DE SPRINT
# ─────────────────────────────────────────────
@app.route("/api/session/start-sprint", methods=["POST"])
def start_sprint_session():
    """
    Abre um terminal com o coia carregado com as skills padrão e um resumo
    da sprint como contexto inicial. O agente NÃO executa nada automaticamente
    — apenas apresenta um super-resumo da sprint e aguarda o usuário.
    """
    body = request.get_json(silent=True) or {}
    sprint_name = body.get("sprint", "").strip()
    extra_skills = body.get("skills", [])

    if not sprint_name:
        return jsonify({"error": "Nome da sprint obrigatório"}), 400

    sprint_path = os.path.join(SPRINTS_DIR, f"{sprint_name}.yaml")
    if not os.path.exists(sprint_path):
        return jsonify({"error": f"Sprint '{sprint_name}' não encontrada"}), 404

    try:
        with open(sprint_path, "r", encoding="utf-8") as f:
            sprint_data = yaml.safe_load(f) or {}
    except Exception as e:
        return jsonify({"error": f"Erro ao ler sprint: {e}"}), 500

    # Skills padrão + adicionais sem duplicatas
    default_skills = [
        "agent-performance",
        "clean-code",
        "install-on-demand",
        "coia-task-manager",
        "jira-sprint-closure",
        "META-github-repos-map",
        "prod-safety",
    ]
    all_skills = default_skills + [s for s in extra_skills if s not in default_skills]
    skills_arg = f'--skills "[{",".join(all_skills)}]"'

    # Monta resumo estruturado da sprint — apenas dados objetivos, sem instruções de ação
    title       = sprint_data.get("title", sprint_name)
    status      = sprint_data.get("status", "open")
    description = (sprint_data.get("description") or "").strip()[:300]
    tasks       = [t for t in (sprint_data.get("tasks") or []) if isinstance(t, dict)]

    tasks_summary_lines = []
    for t in tasks:
        t_title  = t.get("title", "")
        t_status = t.get("status", "open")
        tasks_summary_lines.append(f"  - [{t_status}] {t_title}")
    tasks_summary = "\n".join(tasks_summary_lines) if tasks_summary_lines else "  (sem tarefas)"

    context = (
        f"Sprint carregada: {title}\n"
        f"Arquivo: {sprint_path}\n"
        f"Status: {status}\n"
        f"Descrição: {description}\n"
        f"Tarefas ({len(tasks)}):\n{tasks_summary}\n\n"
        f"Faça um super-resumo desta sprint para o usuário e aguarde."
    )

    import tempfile
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    tmp.write(context)
    tmp.flush()
    tmp_path = tmp.name
    tmp.close()

    cmd = f'coia {skills_arg} --context-file {tmp_path} --no-clear'

    try:
        subprocess.Popen(
            [
                "gnome-terminal", "--",
                "bash", "-i", "-c",
                f'{cmd}; _rc=$?; echo ""; if [ $_rc -ne 0 ]; then echo "── erro (exit $_rc) — pressione qualquer tecla para fechar ──"; else echo "── sessão encerrada ──"; fi; read -n1',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return jsonify({"ok": True, "sprint": sprint_name, "skills": all_skills})
    except FileNotFoundError:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return jsonify({"error": "gnome-terminal não encontrado no sistema"}), 500
    except Exception as e:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
if __name__ == "__main__":
    os.makedirs(SKILLS_DIR, exist_ok=True)
    os.makedirs(CREWS_DIR, exist_ok=True)
    os.makedirs(COMMANDS_DIR, exist_ok=True)
    os.makedirs(PROMPTS_DIR, exist_ok=True)
    os.makedirs(SPRINTS_DIR, exist_ok=True)
    os.makedirs(EXECUTIONS_DIR, exist_ok=True)
    print("🚀 COIA Panel rodando em http://localhost:5005")
    app.run(host="0.0.0.0", port=5005, debug=True, threaded=True)
