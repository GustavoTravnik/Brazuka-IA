"""
DaemonClient
============
Cliente TCP leve para comunicar com o COIA Execution Daemon.

O server.py usa este módulo — nunca fala diretamente com subprocessos.
Se o daemon não estiver rodando, este módulo o inicia automaticamente
como processo independente (sobrevive ao fechamento do painel web).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from dotenv import dotenv_values

DAEMON_HOST      = "127.0.0.1"
DAEMON_PORT_FILE = Path(__file__).parent.parent / "executions" / ".daemon.port"
EXEC_DIR         = Path(__file__).parent.parent / "executions"
ENCODING         = "utf-8"
CONNECT_TIMEOUT  = 3.0
_STARTUP_WAIT    = 8.0   # segundos para o daemon subir

# Caminho absoluto do .env — garante que qualquer subprocesso ache as variáveis
# independente do cwd de quem o lançou.
_ENV_FILE = Path(__file__).parent.parent / ".env"


def _build_env() -> dict[str, str]:
    """
    Monta o environment completo para subprocessos:
    os.environ (variáveis do shell) + .env (arquivo do projeto).
    O .env tem precedência para garantir que as credenciais do projeto
    sempre estejam presentes, mesmo que o shell não as tenha exportado.
    """
    env = dict(os.environ)
    if _ENV_FILE.exists():
        env.update({k: v for k, v in dotenv_values(_ENV_FILE).items() if v is not None})
    return env


class DaemonClient:
    """Fachada para todas as operações com o daemon."""

    # ── Conexão e bootstrap ───────────────────────────────────────────────────

    def _port(self) -> int:
        if DAEMON_PORT_FILE.exists():
            try:
                return int(DAEMON_PORT_FILE.read_text(encoding=ENCODING).strip())
            except ValueError:
                pass
        return 17321

    def _send(self, payload: dict) -> dict:
        """Envia um request e retorna a resposta. Tenta subir o daemon se necessário."""
        for attempt in range(2):
            try:
                port = self._port()
                with socket.create_connection((DAEMON_HOST, port), timeout=CONNECT_TIMEOUT) as s:
                    s.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode(ENCODING))
                    with s.makefile("r", encoding=ENCODING) as f:
                        raw = f.readline()
                    return json.loads(raw)
            except (ConnectionRefusedError, OSError):
                if attempt == 0:
                    self._ensure_daemon_running()
                    time.sleep(1.5)
                else:
                    raise RuntimeError("Daemon não respondeu após inicialização")

    def _is_daemon_alive(self) -> bool:
        """Tenta um ping direto no socket sem disparar bootstrap. Retorna True se respondeu."""
        try:
            port = self._port()
            with socket.create_connection((DAEMON_HOST, port), timeout=CONNECT_TIMEOUT) as s:
                s.sendall((json.dumps({"action": "ping"}, ensure_ascii=False) + "\n").encode(ENCODING))
                with s.makefile("r", encoding=ENCODING) as f:
                    raw = f.readline()
            return json.loads(raw).get("pong", False)
        except Exception:
            return False

    def _ensure_daemon_running(self) -> None:
        """Lança o daemon como processo independente se não estiver rodando."""
        # Verifica novamente antes de lançar — evita duplo spawn em concorrência
        if self._is_daemon_alive():
            return

        # Remove port file stale de sessão anterior para evitar conflito de porta
        if DAEMON_PORT_FILE.exists():
            try:
                DAEMON_PORT_FILE.unlink()
            except Exception:
                pass

        daemon_script = Path(__file__).parent / "daemon.py"
        python = sys.executable

        # Plataforma agnóstica: usa DETACHED no Windows, setsid no Unix
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP |
                subprocess.DETACHED_PROCESS
            )
        else:
            kwargs["start_new_session"] = True  # equivalente ao setsid

        EXEC_DIR.mkdir(parents=True, exist_ok=True)
        log_path = EXEC_DIR / "daemon.log"

        with open(log_path, "a", encoding=ENCODING) as log_f:
            subprocess.Popen(
                [python, "-u", str(daemon_script)],
                stdout=log_f,
                stderr=log_f,
                stdin=subprocess.DEVNULL,
                env=_build_env(),
                cwd=str(Path(__file__).parent.parent),
                **kwargs,
            )

        # Aguarda o daemon gravar a porta em disco e responder ao ping
        deadline = time.monotonic() + _STARTUP_WAIT
        while time.monotonic() < deadline:
            if self._is_daemon_alive():
                return
            time.sleep(0.4)
        raise RuntimeError("Daemon não iniciou no tempo esperado")

    def ping(self) -> bool:
        try:
            return self._send({"action": "ping"}).get("pong", False)
        except Exception:
            return False

    # ── API de execuções ──────────────────────────────────────────────────────

    def start(self, exec_id: str, cmd: list[str], cwd: str) -> dict:
        return self._send({
            "action":   "start",
            "exec_id":  exec_id,
            "cmd":      cmd,
            "cwd":      cwd,
            "exec_dir": str(EXEC_DIR),
        })

    def stop(self, exec_id: str) -> dict:
        return self._send({"action": "stop", "exec_id": exec_id})

    def send_stdin(self, exec_id: str, text: str) -> dict:
        return self._send({"action": "stdin", "exec_id": exec_id, "text": text})

    def status(self, exec_id: str) -> dict:
        return self._send({
            "action":   "status",
            "exec_id":  exec_id,
            "exec_dir": str(EXEC_DIR),
        })

    def logs(self, exec_id: str, since: int = 0) -> dict:
        return self._send({
            "action":   "logs",
            "exec_id":  exec_id,
            "since":    since,
            "exec_dir": str(EXEC_DIR),
        })

    def list_running(self) -> list[dict]:
        r = self._send({"action": "list"})
        return r.get("processes", [])


# Instância global — server.py importa e usa direto
daemon = DaemonClient()
