"""
COIA Execution Daemon
=====================
Supervisor de processos agnóstico de OS (Linux / Windows / macOS).

Cada execução de sprint roda como um processo filho gerenciado por este daemon.
O daemon persiste stdout em disco e expõe uma API JSON minimalista via socket TCP
local (127.0.0.1) para que o painel web conecte, desconecte e reconecte à vontade
sem interromper o processo em execução.

Protocolo (linha a linha, JSON):
  Cliente → Daemon:
    {"action": "start",  "exec_id": "...", "cmd": [...], "cwd": "...", "stdin_pipe": true}
    {"action": "stdin",  "exec_id": "...", "text": "y"}
    {"action": "stop",   "exec_id": "..."}
    {"action": "status", "exec_id": "..."}
    {"action": "logs",   "exec_id": "...", "since": 0}
    {"action": "list"}
    {"action": "ping"}

  Daemon → Cliente:
    {"ok": true, ...}
    {"error": "mensagem"}

O daemon é iniciado automaticamente pelo server.py na primeira requisição que precisar
dele. Ele persiste como processo separado — fechar o painel não o encerra.

Arquivo de lock: executions/<exec_id>.daemon.json  (estado do processo)
Logs em disco:   executions/<exec_id>.log           (append-only, uma linha por entrada)
"""

from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from datetime import datetime, timezone
from dotenv import dotenv_values

# Carrega o .env com path absoluto — o daemon é um processo independente
# e pode ter sido iniciado sem as variáveis de ambiente do shell do usuário.
_ENV_FILE = Path(__file__).parent.parent / ".env"
if _ENV_FILE.exists():
    for _k, _v in dotenv_values(_ENV_FILE).items():
        if _v is not None and _k not in os.environ:
            os.environ[_k] = _v

# ── Configuração ─────────────────────────────────────────────────────────────
DAEMON_HOST = "127.0.0.1"
DAEMON_PORT = 17321          # porta fixa local — só acessível via loopback
DAEMON_PORT_FILE = Path(__file__).parent.parent / "executions" / ".daemon.port"
ENCODING = "utf-8"
LOG_FLUSH_LINES = 10        # flush a cada N linhas novas


# ── Estado global do daemon ───────────────────────────────────────────────────
_processes: dict[str, "_ManagedProcess"] = {}
_lock = threading.Lock()


class _ManagedProcess:
    """Encapsula um subprocesso gerenciado com captura de stdout e fila de stdin."""

    def __init__(self, exec_id: str, cmd: list[str], cwd: str, log_path: Path, state_path: Path):
        self.exec_id    = exec_id
        self.cmd        = cmd
        self.cwd        = cwd
        self.log_path   = log_path
        self.state_path = state_path
        self.proc: subprocess.Popen | None = None
        self.stdin_q: queue.Queue[str] = queue.Queue()
        self.logs: list[str] = []
        self.status = "starting"
        self.started_at  = _now()
        self.finished_at = ""
        self._log_lock = threading.Lock()

    # ── Ciclo de vida ─────────────────────────────────────────────────────────

    def start(self) -> None:
        self._save_state()
        self.proc = subprocess.Popen(
            self.cmd,
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=ENCODING,
            bufsize=1,
        )
        self.status = "running"
        self._save_state()

        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._write_stdin, daemon=True).start()

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.status = "stopped"
        self.finished_at = _now()
        self._save_state()

    def send_stdin(self, text: str) -> bool:
        """Enfileira linha para envio ao stdin do processo. Retorna False se não está rodando."""
        if self.proc and self.proc.poll() is None:
            self.stdin_q.put(text)
            return True
        return False

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def get_logs(self, since: int = 0) -> list[str]:
        with self._log_lock:
            return self.logs[since:]

    # ── Threads internas ──────────────────────────────────────────────────────

    def _read_stdout(self) -> None:
        unflushed = 0
        try:
            for raw in self.proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                with self._log_lock:
                    self.logs.append(line)
                    unflushed += 1
                # Append-only no arquivo de log — não reescreve tudo
                with self.log_path.open("a", encoding=ENCODING) as f:
                    f.write(line + "\n")
                if unflushed >= LOG_FLUSH_LINES:
                    self._save_state()
                    unflushed = 0
        except Exception:
            pass
        finally:
            rc = self.proc.wait()
            self.status = "success" if rc == 0 else "error"
            self.finished_at = _now()
            self._save_state()
            with _lock:
                _processes.pop(self.exec_id, None)

    def _write_stdin(self) -> None:
        while self.is_running():
            try:
                text = self.stdin_q.get(timeout=0.5)
                if self.proc and self.proc.stdin:
                    self.proc.stdin.write(text + "\n")
                    self.proc.stdin.flush()
                    self._append_log(f"[stdin] → '{text}'")
            except queue.Empty:
                continue
            except OSError:
                break

    def _append_log(self, line: str) -> None:
        with self._log_lock:
            self.logs.append(line)
        with self.log_path.open("a", encoding=ENCODING) as f:
            f.write(line + "\n")

    # ── Persistência ──────────────────────────────────────────────────────────

    def _save_state(self) -> None:
        """Persiste o estado do processo (sem os logs — esses ficam no .log)."""
        state = {
            "exec_id":     self.exec_id,
            "cmd":         self.cmd,
            "cwd":         self.cwd,
            "status":      self.status,
            "started_at":  self.started_at,
            "finished_at": self.finished_at,
            "pid":         self.proc.pid if self.proc else None,
        }
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding=ENCODING)
        tmp.replace(self.state_path)


# ── Servidor TCP ──────────────────────────────────────────────────────────────

def _handle_client(conn: socket.socket) -> None:
    """Trata uma conexão de cliente: lê uma linha JSON, responde uma linha JSON."""
    try:
        conn.settimeout(30)
        with conn.makefile("r", encoding=ENCODING) as rf:
            raw = rf.readline()
        if not raw:
            return
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            _reply(conn, {"error": "JSON inválido"})
            return

        action = req.get("action", "")

        if action == "ping":
            _reply(conn, {"ok": True, "pong": True})

        elif action == "list":
            with _lock:
                items = [
                    {"exec_id": p.exec_id, "status": p.status,
                     "started_at": p.started_at, "finished_at": p.finished_at}
                    for p in _processes.values()
                ]
            _reply(conn, {"ok": True, "processes": items})

        elif action == "start":
            exec_id    = req["exec_id"]
            cmd        = req["cmd"]
            cwd        = req.get("cwd", ".")
            exec_dir   = Path(req.get("exec_dir", "."))
            log_path   = exec_dir / f"{exec_id}.log"
            state_path = exec_dir / f"{exec_id}.daemon.json"

            with _lock:
                existing = _processes.get(exec_id)
                # Só rejeita se o processo realmente ainda está vivo
                if existing and existing.is_running():
                    _reply(conn, {"error": "exec_id já está rodando"}); return
                # Processo morto ou inexistente — limpa e recria
                if existing:
                    _processes.pop(exec_id, None)
                # Trunca o log anterior para não misturar com a nova execução
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text("", encoding=ENCODING)
                mp = _ManagedProcess(exec_id, cmd, cwd, log_path, state_path)
                _processes[exec_id] = mp

            mp.start()
            _reply(conn, {"ok": True, "exec_id": exec_id, "pid": mp.proc.pid if mp.proc else None})

        elif action == "stdin":
            exec_id = req["exec_id"]
            text    = req.get("text", "")
            with _lock:
                mp = _processes.get(exec_id)
            if not mp:
                # Processo pode ter terminado — tenta carregar do disco para dar erro claro
                _reply(conn, {"error": "Processo não encontrado ou já encerrado"}); return
            ok = mp.send_stdin(text)
            _reply(conn, {"ok": ok})

        elif action == "stop":
            exec_id = req["exec_id"]
            with _lock:
                mp = _processes.pop(exec_id, None)
            if mp:
                mp.stop()
                _reply(conn, {"ok": True})
            else:
                _reply(conn, {"error": "Processo não encontrado"}); return

        elif action == "status":
            exec_id = req["exec_id"]
            with _lock:
                mp = _processes.get(exec_id)
            if mp:
                _reply(conn, {"ok": True, "exec_id": exec_id, "status": mp.status,
                              "started_at": mp.started_at, "finished_at": mp.finished_at,
                              "pid": mp.proc.pid if mp.proc else None})
            else:
                # Tenta ler do arquivo de estado em disco
                state = _load_state_file(req.get("exec_dir", "."), exec_id)
                if state:
                    _reply(conn, {"ok": True, **state})
                else:
                    _reply(conn, {"error": "Processo não encontrado"})

        elif action == "logs":
            exec_id = req["exec_id"]
            since   = int(req.get("since", 0))
            with _lock:
                mp = _processes.get(exec_id)
            if mp:
                logs = mp.get_logs(since)
                _reply(conn, {"ok": True, "logs": logs, "total": len(mp.logs), "status": mp.status})
            else:
                # Lê direto do arquivo .log em disco
                log_path = Path(req.get("exec_dir", ".")) / f"{exec_id}.log"
                state    = _load_state_file(req.get("exec_dir", "."), exec_id)
                all_logs = _read_log_file(log_path)
                status   = state.get("status", "unknown") if state else "unknown"
                _reply(conn, {"ok": True, "logs": all_logs[since:], "total": len(all_logs), "status": status})

        else:
            _reply(conn, {"error": f"action desconhecida: {action}"})

    except Exception as e:
        try:
            _reply(conn, {"error": str(e)})
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _reply(conn: socket.socket, data: dict) -> None:
    msg = json.dumps(data, ensure_ascii=False) + "\n"
    conn.sendall(msg.encode(ENCODING))


def _load_state_file(exec_dir: str, exec_id: str) -> dict | None:
    path = Path(exec_dir) / f"{exec_id}.daemon.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding=ENCODING))
    except Exception:
        return None


def _read_log_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return [l.rstrip() for l in path.read_text(encoding=ENCODING).splitlines() if l.strip()]
    except Exception:
        return []


def _run_server(port: int) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((DAEMON_HOST, port))
    srv.listen(32)
    # Salva a porta em disco para que o server.py saiba onde conectar
    DAEMON_PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    DAEMON_PORT_FILE.write_text(str(port), encoding=ENCODING)
    print(f"[COIA Daemon] ouvindo em {DAEMON_HOST}:{port}", flush=True)
    while True:
        try:
            conn, _ = srv.accept()
            threading.Thread(target=_handle_client, args=(conn,), daemon=True).start()
        except Exception:
            pass


def _find_free_port(start: int = DAEMON_PORT) -> int:
    """Encontra uma porta livre a partir de `start`."""
    for port in range(start, start + 100):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind((DAEMON_HOST, port))
            s.close()
            return port
        except OSError:
            continue
    raise RuntimeError("Nenhuma porta livre encontrada no range 17321-17421")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Reconciliação de estado ao subir ─────────────────────────────────────────

def _reconcile_stale_processes() -> None:
    """
    Ao iniciar, varre todos os .daemon.json em disco e corrige estados fantasmas.

    Um processo é considerado morto se:
      - status == "running" (ou "starting") no arquivo, E
      - o PID salvo não existe mais no sistema operacional.

    Nesses casos, o status é corrigido para "crashed" no .daemon.json,
    sinalizando ao server.py que o processo não sobreviveu ao reboot.
    """
    exec_dir = DAEMON_PORT_FILE.parent  # executions/
    if not exec_dir.exists():
        return

    for state_path in exec_dir.glob("*.daemon.json"):
        try:
            state = json.loads(state_path.read_text(encoding=ENCODING))
        except Exception:
            continue

        if state.get("status") not in ("running", "starting"):
            continue  # já tem status final — não mexe

        pid = state.get("pid")
        if pid and _pid_alive(pid):
            continue  # processo realmente existe — não mexe

        # PID morto com status "running" → fantasma de reboot
        state["status"]      = "crashed"
        state["finished_at"] = _now()
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding=ENCODING)
        tmp.replace(state_path)
        print(f"[COIA Daemon] reconciliado: {state['exec_id']} (pid={pid}) → crashed", flush=True)


def _pid_alive(pid: int) -> bool:
    """Retorna True se o PID existe e está rodando no OS atual."""
    try:
        if sys.platform == "win32":
            import ctypes
            SYNCHRONIZE = 0x00100000
            handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        else:
            os.kill(pid, 0)   # signal 0 = só testa existência, não mata
            return True
    except (OSError, ProcessLookupError):
        return False


# ── Ponto de entrada (processo daemon independente) ───────────────────────────

if __name__ == "__main__":
    _reconcile_stale_processes()
    port = _find_free_port()
    _run_server(port)
