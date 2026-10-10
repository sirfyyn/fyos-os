"""mcp_hub.plugins.example_echo — minimal reference HubPlugin.

Purpose:
    - Smoke-test the Hub skeleton end-to-end (loader → registry → meta-tool dispatch).
    - Serve as a copy-paste template for real plugins in S-MCP-HUB.1.4+.

Exposes ONE tool:
    ``echo.say(text: str) -> {"echo": str}``
"""

from __future__ import annotations

from typing import Any

from ..plugin import HubPlugin, ToolDescriptor


class EchoPlugin(HubPlugin):
    """Returns its input unchanged. Useful for plumbing-tests."""

    name = "echo"
    description = "Reference plugin — echoes its input back. Used for Hub smoke-tests."
    version = "0.1.0"

    def register(self) -> None:
        # Nothing to warm up. Real plugins would open connections here.
        return None

    def describe_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name="say",
                description="Echo the given text back to the caller.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Arbitrary UTF-8 string to echo.",
                        }
                    },
                    "required": ["text"],
                    "additionalProperties": False,
                },
                tags=["reference", "smoke-test", "read"],
            ),
        ]

    def call(self, method: str, args: dict[str, Any]) -> Any:
        if method != "say":
            raise ValueError(f"EchoPlugin has no tool {method!r}")
        text = args.get("text")
        if not isinstance(text, str):
            raise TypeError("echo.say requires 'text' (str)")
        return {"echo": text}

    def health(self) -> dict[str, Any]:
        return {"ok": True, "status": "healthy", "plugin": self.name}

    def metrics(self) -> dict[str, Any]:
        return {"plugin": self.name, "tools_exposed": 1}
