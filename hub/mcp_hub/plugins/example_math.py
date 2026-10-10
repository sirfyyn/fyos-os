"""mcp_hub.plugins.example_math — second reference HubPlugin (S-MCP-HUB.1.2).

Purpose:
    - Exercise the 1.2 Plugin-Protocol + Circuit-Breaker integration.
    - Provide a crash-ready tool (``math.divide`` with ZeroDivisionError) so
      tests and smoke-checks can trip the circuit-breaker on demand.
    - Serve as a copy-paste template alongside ``example_echo`` for future
      production plugins.

Exposes TWO tools:
    ``math.add(a: float, b: float) -> {"sum": float}``
    ``math.divide(a: float, b: float) -> {"quotient": float}``  (ZeroDivisionError when b == 0)
"""

from __future__ import annotations

from typing import Any

from ..plugin import HubPlugin, ToolDescriptor


class MathPlugin(HubPlugin):
    """Tiny arithmetic plugin. Intentionally crash-prone on divide-by-zero."""

    name = "math"
    description = "Reference plugin — basic arithmetic (add, divide). Crashes on divide-by-zero."
    version = "0.1.0"

    # --- lifecycle ---------------------------------------------------------

    def register(self) -> None:
        # No connections to open — pure function plugin.
        return None

    def init(self) -> None:
        # No cross-plugin wiring needed.
        return None

    def shutdown(self) -> None:
        return None

    # --- tool descriptors --------------------------------------------------

    def describe_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name="add",
                description="Return the sum of two numbers (a + b).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "a": {"type": "number", "description": "First summand."},
                        "b": {"type": "number", "description": "Second summand."},
                    },
                    "required": ["a", "b"],
                    "additionalProperties": False,
                },
                tags=["reference", "arithmetic", "read"],
            ),
            ToolDescriptor(
                name="divide",
                description="Return a / b. Raises ZeroDivisionError when b == 0 "
                "(used to exercise the Hub circuit-breaker).",
                input_schema={
                    "type": "object",
                    "properties": {
                        "a": {"type": "number", "description": "Dividend."},
                        "b": {"type": "number", "description": "Divisor — 0 triggers crash."},
                    },
                    "required": ["a", "b"],
                    "additionalProperties": False,
                },
                tags=["reference", "arithmetic", "crash-test", "read"],
            ),
        ]

    # --- dispatch ----------------------------------------------------------

    def call(self, method: str, args: dict[str, Any]) -> Any:
        if method == "add":
            a, b = _coerce_numeric_pair(args, "add")
            return {"sum": a + b}
        if method == "divide":
            a, b = _coerce_numeric_pair(args, "divide")
            # Intentional — let ZeroDivisionError propagate so the Hub can
            # record a failure on the circuit-breaker.
            return {"quotient": a / b}
        raise ValueError(f"MathPlugin has no tool {method!r}")

    # --- observability -----------------------------------------------------

    def health(self) -> dict[str, Any]:
        return {"ok": True, "status": "healthy", "plugin": self.name}

    def metrics(self) -> dict[str, Any]:
        return {"plugin": self.name, "tools_exposed": 2}


def _coerce_numeric_pair(args: dict[str, Any], tool: str) -> tuple[float, float]:
    """Validate + coerce the ``a`` / ``b`` arguments shared by add/divide."""
    if not isinstance(args, dict):
        raise TypeError(f"math.{tool} requires a dict of arguments")
    if "a" not in args or "b" not in args:
        raise TypeError(f"math.{tool} requires both 'a' and 'b'")
    try:
        a = float(args["a"])
        b = float(args["b"])
    except (TypeError, ValueError) as exc:
        raise TypeError(f"math.{tool} requires numeric 'a' and 'b': {exc}") from exc
    return a, b
