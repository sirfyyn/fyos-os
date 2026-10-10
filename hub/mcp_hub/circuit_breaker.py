"""mcp_hub.circuit_breaker — per-plugin Hystrix-like circuit-breaker.

Prevents cascading failures when a plugin misbehaves. Each plugin gets its own
CircuitBreaker instance — a failure in plugin A must NEVER trip plugin B.

State machine:

    CLOSED  ──5 failures──► OPEN  ──timeout──► HALF_OPEN
       ▲                                          │
       └────── N half_open_successes ◄───────────┘
                                                  │
                               any failure ──────►┘ (back to OPEN)

- CLOSED:    normal operation. count failures.
- OPEN:      fast-fail every call for ``timeout_sec``. No plugin invocation.
- HALF_OPEN: allow up to ``half_open_max_calls`` trial calls. If ALL succeed
             → CLOSED; first failure → OPEN (reset timer).

Threading:
    Breaker state is guarded by a ``threading.Lock``. The Hub runs calls
    serially per-plugin today, but async-dispatch in a later sub-item will
    exercise the lock. Keep critical sections tiny.

Config defaults (tuned for in-process FYOS plugins):
    failure_threshold   = 5     (5 consecutive fails trip the breaker)
    timeout_sec         = 30    (wait 30s before probing HALF_OPEN)
    half_open_max_calls = 3     (3 successes needed to close)

Example:
    >>> cb = CircuitBreaker(name="math")
    >>> cb.allow_call()
    True
    >>> for _ in range(5): cb.record_failure()
    >>> cb.state
    <CircuitState.OPEN: 'open'>
    >>> cb.allow_call()
    False
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Three-state machine."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Per-plugin or global circuit-breaker tuning."""

    failure_threshold: int = 5
    """Consecutive failures in CLOSED-state that trip the breaker to OPEN."""

    timeout_sec: float = 30.0
    """Seconds to stay in OPEN-state before allowing HALF_OPEN probes."""

    half_open_max_calls: int = 3
    """Consecutive successes in HALF_OPEN needed to transition back to CLOSED.

    A single failure in HALF_OPEN resets the breaker to OPEN.
    """

    enabled: bool = True
    """Master-switch. When False, allow_call() always returns True + record_*
    methods are no-ops (used by tests that want raw-dispatch without breaker)."""


class CircuitBreaker:
    """Per-plugin circuit-breaker instance. Thread-safe."""

    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state: CircuitState = CircuitState.CLOSED
        self._consecutive_failures: int = 0
        self._half_open_successes: int = 0
        self._opened_at: Optional[float] = None  # monotonic timestamp
        self._lock = threading.Lock()
        self._total_opens: int = 0  # for metrics

    # --- state queries -----------------------------------------------------

    @property
    def state(self) -> CircuitState:
        """Return current state, auto-transitioning OPEN→HALF_OPEN if timeout elapsed."""
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    def snapshot(self) -> dict:
        """Read-only telemetry snapshot — safe to call from metrics / health probes."""
        with self._lock:
            self._maybe_transition_to_half_open()
            return {
                "name": self.name,
                "state": self._state.value,
                "consecutive_failures": self._consecutive_failures,
                "half_open_successes": self._half_open_successes,
                "opened_at": self._opened_at,
                "total_opens": self._total_opens,
                "enabled": self.config.enabled,
            }

    # --- gate --------------------------------------------------------------

    def allow_call(self) -> bool:
        """Return True if a call is currently permitted under the breaker."""
        if not self.config.enabled:
            return True
        with self._lock:
            self._maybe_transition_to_half_open()
            if self._state is CircuitState.OPEN:
                return False
            # CLOSED + HALF_OPEN both permit calls. HALF_OPEN has an implicit
            # concurrency cap equal to half_open_max_calls — but since the Hub
            # dispatches serially per-plugin today, no trial-slot counting is
            # required. A later async sub-item will add a semaphore.
            return True

    # --- outcome recording -------------------------------------------------

    def record_success(self) -> None:
        """Called after a successful plugin invocation."""
        if not self.config.enabled:
            return
        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self.config.half_open_max_calls:
                    self._transition(CircuitState.CLOSED)
            else:
                # CLOSED: reset failure-counter.
                self._consecutive_failures = 0

    def record_failure(self) -> None:
        """Called after a failed plugin invocation (raised exception)."""
        if not self.config.enabled:
            return
        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                # Any failure in HALF_OPEN re-opens the breaker immediately.
                self._transition(CircuitState.OPEN)
                return
            if self._state is CircuitState.CLOSED:
                self._consecutive_failures += 1
                if self._consecutive_failures >= self.config.failure_threshold:
                    self._transition(CircuitState.OPEN)
            # OPEN: no-op (already open, timer running).

    # --- test / admin helpers ----------------------------------------------

    def force_reset(self) -> None:
        """Admin-only: force back to CLOSED state. Used by admin-tool in 1.3+."""
        with self._lock:
            self._transition(CircuitState.CLOSED)

    # --- internals ---------------------------------------------------------

    def _maybe_transition_to_half_open(self) -> None:
        """If OPEN + timeout elapsed → HALF_OPEN. Must be called under _lock."""
        if self._state is CircuitState.OPEN and self._opened_at is not None:
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.config.timeout_sec:
                self._transition(CircuitState.HALF_OPEN)

    def _transition(self, new_state: CircuitState) -> None:
        """State transition helper. Must be called under _lock."""
        old = self._state
        if old is new_state:
            return
        self._state = new_state
        if new_state is CircuitState.OPEN:
            self._opened_at = time.monotonic()
            self._half_open_successes = 0
            self._total_opens += 1
            logger.warning(
                "circuit-breaker[%s]: %s → OPEN (failures=%d threshold=%d)",
                self.name,
                old.value,
                self._consecutive_failures,
                self.config.failure_threshold,
            )
        elif new_state is CircuitState.HALF_OPEN:
            self._half_open_successes = 0
            logger.info(
                "circuit-breaker[%s]: %s → HALF_OPEN (probing after %.1fs)",
                self.name,
                old.value,
                self.config.timeout_sec,
            )
        elif new_state is CircuitState.CLOSED:
            self._consecutive_failures = 0
            self._half_open_successes = 0
            self._opened_at = None
            logger.info(
                "circuit-breaker[%s]: %s → CLOSED (recovered)",
                self.name,
                old.value,
            )


# ---------------------------------------------------------------------------
# Registry helper — one breaker per plugin-name.
# ---------------------------------------------------------------------------


@dataclass
class BreakerRegistry:
    """Keeps one CircuitBreaker instance per plugin-name. Lazy-initialized.

    The registry.py builder instantiates this once per Hub-build and hands it
    to ``dispatch()``. Tests may create bare instances.
    """

    default_config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    breakers: dict[str, CircuitBreaker] = field(default_factory=dict)

    def get(self, plugin_name: str) -> CircuitBreaker:
        cb = self.breakers.get(plugin_name)
        if cb is None:
            cb = CircuitBreaker(name=plugin_name, config=self.default_config)
            self.breakers[plugin_name] = cb
        return cb

    def snapshot_all(self) -> list[dict]:
        return [cb.snapshot() for cb in self.breakers.values()]
