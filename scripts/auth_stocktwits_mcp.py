"""Authorize and verify the official Stocktwits remote MCP connection."""

from __future__ import annotations

import asyncio
import json
import queue
import sys
import webbrowser
from collections.abc import Sequence
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Lock
from urllib.parse import parse_qs, urlsplit

from src.adapters import (
    MCPTransportError,
    StocktwitsSentimentProvider,
    build_stocktwits_mcp_transport,
)
from src.core import load_settings


class _LoopbackOAuthCallback:
    """Receive exactly one OAuth callback without logging its query string."""

    def __init__(self, redirect_uri: str, *, timeout_seconds: float) -> None:
        parsed = urlsplit(redirect_uri)
        if parsed.hostname is None or parsed.port is None:
            raise ValueError("Stocktwits OAuth redirect URI requires an explicit port")
        self._path = parsed.path
        self._result: queue.Queue[tuple[str, str | None] | Exception] = queue.Queue(
            maxsize=1
        )
        self._server = HTTPServer(
            (parsed.hostname, parsed.port),
            self._handler_type(),
        )
        self._server.timeout = timeout_seconds
        self._close_lock = Lock()
        self._closed = False

    async def redirect(self, authorization_url: str) -> None:
        """Show the SDK-issued URL and ask the system browser to open it."""

        opened = webbrowser.open(authorization_url)
        if not opened:
            raise RuntimeError("Stocktwits authorization browser could not be opened")
        print("authorization_required = approve Stocktwits access in the browser")

    async def callback(self) -> tuple[str, str | None]:
        """Wait for one callback and return only code/state to the SDK."""

        await asyncio.to_thread(self._server.handle_request)
        try:
            result = self._result.get_nowait()
        except queue.Empty:
            raise RuntimeError("Stocktwits OAuth callback timed out") from None
        finally:
            self.close()
        if isinstance(result, Exception):
            raise result
        return result

    def close(self) -> None:
        """Close the loopback listener once."""

        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._server.server_close()

    def _handler_type(self) -> type[BaseHTTPRequestHandler]:
        expected_path = self._path
        result_queue = self._result

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlsplit(self.path)
                values = parse_qs(parsed.query)
                code = values.get("code", [None])[0]
                state = values.get("state", [None])[0]
                error = values.get("error", [None])[0]
                if parsed.path != expected_path or error or not code:
                    result: tuple[str, str | None] | Exception = RuntimeError(
                        "Stocktwits OAuth authorization was not completed"
                    )
                    status = 400
                    body = b"Stocktwits authorization failed. Return to the terminal."
                else:
                    result = (code, state)
                    status = 200
                    body = b"Stocktwits authorization complete. You may close this tab."
                try:
                    result_queue.put_nowait(result)
                except queue.Full:
                    status = 409
                    body = b"OAuth callback was already processed."
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        return CallbackHandler


async def _authorize() -> dict[str, object]:
    settings = load_settings().providers
    authorization_timeout = max(settings.stocktwits_mcp_timeout_seconds, 300.0)
    callback = _LoopbackOAuthCallback(
        settings.stocktwits_mcp_redirect_uri,
        timeout_seconds=authorization_timeout,
    )
    transport = build_stocktwits_mcp_transport(
        settings,
        interactive_auth=True,
        timeout_seconds=authorization_timeout,
        redirect_handler=callback.redirect,
        callback_handler=callback.callback,
    )
    try:
        await transport.initialize()
        tools = await transport.list_tools()
    finally:
        callback.close()
        await transport.close()
    required = set(StocktwitsSentimentProvider.required_tools)
    return {
        "authentication": "PASS",
        "mcp_initialize": "PASS",
        "tool_count": len(tools),
        "available_tool_names": list(tools),
        "required_tools_available": required.issubset(tools),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run interactive OAuth and print credential-free diagnostics."""

    del argv
    try:
        result = asyncio.run(_authorize())
    except (MCPTransportError, OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "authentication": "FAIL",
                    "mcp_initialize": "FAIL",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["required_tools_available"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
