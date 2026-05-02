"""
COIA Cron Scheduler
===================
Roda em background dentro do processo do server.py.
Varre os arquivos YAML em crons/ a cada 30s, avalia as cron expressions
e dispara execuções via daemon quando o horário bate.

Cada cron YAML tem o formato:
  name:        str
  expression:  str   (cron expression — 5 campos: min hour dom month dow)
  prompt:      str
  model:       str   (ex: gemini-1.5-flash)
  skills:      list[str]
  mcps:        list[str] | null   (null = todos, [] = nenhum)
  enabled:     bool  (default true)

O scheduler mantém em memória o último horário de disparo por cron (last_fired)
para garantir que cada janela de 1 minuto dispare no máximo uma vez, mesmo que
o loop rode mais de uma vez dentro do mesmo minuto.
"""

from __future__ import annotations

import glob
import json
import os
import sys
import threading
import time
import uuid
import yaml
from datetime import datetime, timezone
from pathlib import Path

# croniter é opcional — instalado via requirements.txt
try:
    from croniter import croniter
    _CRONITER_OK = True
except ImportError:
    _CRONITER_OK = False
    print("[cron] AVISO: croniter não instalado — crons não serão disparadas. Execute: pip install croniter")

CRONS_DIR      = Path(__file__).parent.parent / "crons"
EXECUTIONS_DIR = Path(__file__).parent.parent / "executions"
BASE_DIR       = Path(__file__).parent.parent
APP_PY         = BASE_DIR / "app.py"

_TICK = 30          # segundos entre verificações
_last_fired: dict[str, str] = {}   # cron_name → "YYYY-MM-DD HH:MM" último disparo
_lock = threading.Lock()
_running = False
_thread: threading.Thread | None = None

# Referência ao daemon_client injetada no start() para evitar import circular
_daemon = None


# ── Público ───────────────────────────────────────────────────────────────────

def start(daemon_client) -> None:
    """Inicia o scheduler em thread daemon. Idempotente."""
    global _running, _thread, _daemon
    if _running:
        return
    if not _CRONITER_OK:
        return
    _daemon = daemon_client
    _running = True
    _thread = threading.Thread(target=_loop, daemon=True, name="coia-cron-scheduler")
    _thread.start()
    print("[cron] Scheduler iniciado.")


def stop() -> None:
    global _running
    _running = False


def status() -> dict:
    """Retorna estado atual do scheduler para o endpoint /api/crons/scheduler/status."""
    with _lock:
        fired = dict(_last_fired)
    return {
        "running":     _running,
        "croniter_ok": _CRONITER_OK,
        "last_fired":  fired,
    }


def next_runs(expression: str, count: int = 5) -> list[str]:
    """Retorna as próximas N execuções de uma cron expression (para preview no frontend)."""
    if not _CRONITER_OK:
        return []
    try:
        it = croniter(expression, datetime.now())
        return [it.get_next(datetime).strftime("%Y-%m-%d %H:%M") for _ in range(count)]
    except Exception as e:
        return [f"Erro: {e}"]


# ── Loop interno ──────────────────────────────────────────────────────────────

def _loop() -> None:
    while _running:
        try:
            _tick()
        except Exception as e:
            print(f"[cron] Erro no tick: {e}")
        time.sleep(_TICK)


def _tick() -> None:
    now = datetime.now()
    now_minute = now.strftime("%Y-%m-%d %H:%M")

    cron_files = glob.glob(str(CRONS_DIR / "*.yaml"))
    for path in sorted(cron_files):
        try:
            _evaluate(path, now, now_minute)
        except Exception as e:
            name = Path(path).stem
            print(f"[cron] Erro ao avaliar '{name}': {e}")


def _evaluate(path: str, now: datetime, now_minute: str) -> None:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    name = cfg.get("name") or Path(path).stem
    if not cfg.get("enabled", True):
        return

    expression = (cfg.get("expression") or "").strip()
    if not expression:
        return

    with _lock:
        last = _last_fired.get(name)

    if last == now_minute:
        return  # já disparou neste minuto

    try:
        it = croniter(expression, now)
        prev = it.get_prev(datetime)
    except Exception as e:
        print(f"[cron] Expression inválida em '{name}': {e}")
        return

    if prev.strftime("%Y-%m-%d %H:%M") != now_minute:
        return  # não é hora desta cron

    # ── É hora: dispara ──────────────────────────────────────────────────────
    with _lock:
        _last_fired[name] = now_minute

    print(f"[cron] ⏰ Disparando '{name}' ({now_minute})")
    _fire(name, cfg)


def _fire(name: str, cfg: dict) -> None:
    prompt  = (cfg.get("prompt") or "").strip()
    model   = (cfg.get("model") or "gemini-1.5-flash").strip()
    skills  = cfg.get("skills") or []
    mcps    = cfg.get("mcps")    # None = todos, [] = nenhum

    if not prompt:
        print(f"[cron] '{name}' sem prompt — ignorada.")
        return

    exec_id = f"cron-{uuid.uuid4().hex[:8]}"
    EXECUTIONS_DIR.mkdir(parents=True, exist_ok=True)

    exec_json = EXECUTIONS_DIR / f"{exec_id}.json"
    exec_data = {
        "id":          exec_id,
        "type":        "cron",
        "cron":        name,
        "title":       f"[CRON] {name} — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "status":      "running",
        "created_at":  datetime.now(timezone.utc).isoformat(),
        "started_at":  datetime.now(timezone.utc).isoformat(),
        "finished_at": "",
    }
    exec_json.write_text(json.dumps(exec_data, ensure_ascii=False, indent=2), encoding="utf-8")

    cmd = _build_cmd(prompt, model, skills, mcps)
    print(f"[cron] cmd: {' '.join(cmd)}")

    try:
        result = _daemon.start(exec_id=exec_id, cmd=cmd, cwd=str(BASE_DIR))
        if "error" in result:
            _update_exec_status(exec_id, "error")
            print(f"[cron] Daemon recusou '{name}': {result['error']}")
    except Exception as e:
        _update_exec_status(exec_id, "error")
        print(f"[cron] Falha ao disparar '{name}': {e}")


def _build_cmd(prompt: str, model: str, skills: list[str], mcps) -> list[str]:
    import tempfile

    # Grava o prompt em arquivo temporário para passar via --context-file
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8",
        dir=str(EXECUTIONS_DIR),
    )
    tmp.write(prompt)
    tmp.flush()
    tmp.close()

    cmd = [sys.executable, "-u", str(APP_PY)]

    if skills:
        cmd += ["--skills", f"[{','.join(skills)}]"]

    if mcps is None:
        pass  # todos os MCPs — nenhuma flag
    elif len(mcps) == 0:
        cmd += ["--no-mcp"]
    else:
        cmd += ["--mcps", f"[{','.join(mcps)}]"]

    cmd += ["--model-override", model]
    cmd += ["--context-file", tmp.name]
    cmd += ["--headless"]   # flag que o app.py usa para sair após a primeira resposta

    return cmd


def _update_exec_status(exec_id: str, status: str) -> None:
    path = EXECUTIONS_DIR / f"{exec_id}.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["status"] = status
        data["finished_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
