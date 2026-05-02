"""
rate_limiter.py
───────────────
Controle de cadência de chamadas à API Gemini por modelo.

Motivação
---------
O Developer Portal suspende contas que excedem rate limits por minuto (RPM) ou
daily token limits. Sem controle, a crew dispara chamadas em rajada.

Estratégia
----------
Token-bucket simplificado por modelo: rastreia o timestamp de cada chamada
nos últimos 60 segundos e aplica um delay mínimo antes de liberar a próxima
quando o ritmo está próximo do limite configurado.

Limites padrão (conservadores):
  Flash: 15 RPM
  Pro:    2 RPM
  default: 15 RPM (fallback seguro)

Uso
---
    limiter = RateLimiter()
    await limiter.acquire("gemini-1.5-flash")   # aguarda se necessário
    # ... faz a chamada API ...
"""

from __future__ import annotations

import asyncio
import time
from collections import deque


# ── Limites conservadores por modelo ─────────────────────────────────────────
_RPM_LIMITS: dict[str, int] = {
    "gemini-1.5-flash": 15,
    "gemini-1.5-pro":    2,
}
_DEFAULT_RPM = 15

# Delay mínimo entre chamadas consecutivas ao mesmo modelo (segundos)
_MIN_INTER_CALL_DELAY: dict[str, float] = {
    "gemini-1.5-flash": 1.0,
    "gemini-1.5-pro":   2.0,
}
_DEFAULT_MIN_DELAY = 0.8


def _rpm_for(model: str) -> int:
    for key, rpm in _RPM_LIMITS.items():
        if key in model:
            return rpm
    return _DEFAULT_RPM


def _min_delay_for(model: str) -> float:
    for key, delay in _MIN_INTER_CALL_DELAY.items():
        if key in model:
            return delay
    return _DEFAULT_MIN_DELAY


class RateLimiter:
    """
    Controle de cadência de chamadas API por modelo.

    Thread-safe via asyncio.Lock — seguro para uso em múltiplos agentes
    concorrentes dentro do mesmo event loop.
    """

    def __init__(self) -> None:
        # timestamps das chamadas nos últimos 60s, por modelo
        self._windows: dict[str, deque[float]] = {}
        # timestamp da última chamada por modelo (para min inter-call delay)
        self._last_call: dict[str, float] = {}
        # lock por modelo para serializar o acquire
        self._locks: dict[str, asyncio.Lock] = {}

    def _ensure_model(self, model: str) -> None:
        if model not in self._windows:
            self._windows[model] = deque()
            self._last_call[model] = 0.0
            self._locks[model] = asyncio.Lock()

    async def acquire(self, model: str) -> None:
        """
        Aguarda o tempo necessário antes de liberar uma chamada ao modelo.

        Aplica dois controles:
        1. Delay mínimo entre chamadas consecutivas (anti-burst imediato)
        2. RPM sliding-window de 60 segundos (anti-spray sustentado)
        """
        self._ensure_model(model)
        async with self._locks[model]:
            await self._wait_inter_call(model)
            await self._wait_rpm_window(model)
            # Registra a chamada
            now = time.monotonic()
            self._windows[model].append(now)
            self._last_call[model] = now

    async def _wait_inter_call(self, model: str) -> None:
        """Garante o delay mínimo entre chamadas consecutivas."""
        min_delay = _min_delay_for(model)
        last = self._last_call.get(model, 0.0)
        elapsed = time.monotonic() - last
        if elapsed < min_delay:
            wait = min_delay - elapsed
            await asyncio.sleep(wait)

    async def _wait_rpm_window(self, model: str) -> None:
        """Garante que não ultrapassamos o RPM no sliding window de 60s."""
        rpm_limit = _rpm_for(model)
        window = self._windows[model]

        while True:
            now = time.monotonic()
            # Remove timestamps com mais de 60s
            cutoff = now - 60.0
            while window and window[0] < cutoff:
                window.popleft()

            if len(window) < rpm_limit:
                break  # há espaço na janela — libera

            # Janela cheia: aguarda até o timestamp mais antigo expirar
            oldest = window[0]
            wait = (oldest + 60.0) - now + 0.05  # +50ms de margem
            await asyncio.sleep(max(0.0, wait))

    def stats(self, model: str) -> dict:
        """Retorna estatísticas da janela atual para debug/log."""
        self._ensure_model(model)
        now = time.monotonic()
        window = self._windows[model]
        cutoff = now - 60.0
        active = sum(1 for t in window if t >= cutoff)
        return {
            "model": model,
            "calls_last_60s": active,
            "rpm_limit": _rpm_for(model),
            "utilization_pct": round(active / _rpm_for(model) * 100, 1),
        }
