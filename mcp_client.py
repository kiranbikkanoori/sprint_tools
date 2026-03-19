"""
Shared MCP-over-HTTP client for sprint tools.

Provides the McpClient class for communicating with MCP servers (e.g. Jira)
via the Streamable HTTP transport, plus helpers for locating and loading mcp.json config.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import requests


class McpClient:
    """Minimal MCP-over-HTTP client for calling tools on a Streamable HTTP server."""

    def __init__(self, url: str, headers: dict):
        self.url = url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["Content-Type"] = "application/json"
        self.session.headers["Accept"] = "application/json, text/event-stream"
        self.session.headers.update(headers)
        self.session_id = None
        self._initialize()

    def _initialize(self):
        resp = self._raw_post({
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "sprint-tools", "version": "1.0.0"},
            },
            "id": str(uuid.uuid4()),
        })
        if "Mcp-Session-Id" in resp.headers:
            self.session_id = resp.headers["Mcp-Session-Id"]
            self.session.headers["Mcp-Session-Id"] = self.session_id

        self.session.post(self.url, json={
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }, timeout=15)

    def _raw_post(self, body: dict) -> requests.Response:
        resp = self.session.post(self.url, json=body, timeout=60)
        resp.raise_for_status()
        return resp

    def call_tool(self, tool_name: str, arguments: dict) -> any:
        body = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
            "id": str(uuid.uuid4()),
        }
        resp = self._raw_post(body)
        content_type = resp.headers.get("Content-Type", "")

        if "text/event-stream" in content_type:
            return self._parse_sse(resp.text)
        else:
            data = resp.json()
            return self._extract_result(data)

    def _parse_sse(self, text: str) -> any:
        for line in text.splitlines():
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    result = self._extract_result(data)
                    if result is not None:
                        return result
                except json.JSONDecodeError:
                    continue
        return None

    def _extract_result(self, data: dict) -> any:
        if "error" in data:
            raise RuntimeError(f"MCP error: {data['error']}")
        result = data.get("result", {})
        content = result.get("content", [])
        for item in content:
            if item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except (json.JSONDecodeError, TypeError):
                    return item.get("text")
        return result


def find_mcp_config() -> Path | None:
    """Locate mcp.json by searching standard Cursor config paths."""
    candidates = [
        Path.home() / ".cursor" / "mcp.json",
        Path.cwd().parent / ".cursor" / "mcp.json",
        Path.cwd() / ".cursor" / "mcp.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def load_mcp_server_config(mcp_path: Path, keyword: str) -> tuple[str, dict] | None:
    """
    Extract MCP server URL and headers from mcp.json for the server whose name
    contains *keyword* (case-insensitive) and uses ``type: http``.

    Returns ``(url, headers)`` or ``None`` if not found.
    """
    try:
        data = json.loads(mcp_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    servers = data.get("mcpServers", {})

    for name, cfg in servers.items():
        if keyword.lower() in name.lower() and cfg.get("type") == "http":
            url = cfg["url"]
            headers = cfg.get("headers", {})
            return url, headers
    return None
