"""Reusable official-SDK MCP client transport and secure local OAuth state."""

from __future__ import annotations

import json
import os
import time
import traceback
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession, types
from mcp.client.auth import (
    OAuthClientProvider,
    OAuthFlowError,
    OAuthRegistrationError,
    OAuthTokenError,
)
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)
from mcp.shared.exceptions import McpError
from pydantic import AnyUrl, ValidationError


class MCPTransportError(RuntimeError):
    """Safe public MCP transport failure without response or token details."""


class MCPAuthorizationRequiredError(MCPTransportError):
    """Raised when an interactive OAuth grant is required."""


class MCPInitializationError(MCPTransportError):
    """Raised when an MCP session cannot initialize."""


class MCPToolError(MCPTransportError):
    """Raised when an allowed MCP tool call fails or is malformed."""


@dataclass(frozen=True, slots=True)
class MCPToolResult:
    """Provider-neutral JSON object returned by one successful MCP tool."""

    data: Mapping[str, object]


class MCPTransport(Protocol):
    """Minimal asynchronous MCP lifecycle consumed by Data Providers."""

    async def initialize(self) -> None:
        """Open and initialize one MCP session."""

    async def list_tools(self) -> tuple[str, ...]:
        """Return every tool name advertised by the initialized server."""

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> MCPToolResult:
        """Call one advertised tool and return validated JSON data."""

    async def close(self) -> None:
        """Close the MCP session and underlying HTTP resources."""


class MCPTokenStorage(Protocol):
    """OAuth state contract required by the official MCP SDK."""

    async def get_tokens(self) -> OAuthToken | None: ...

    async def set_tokens(self, tokens: OAuthToken) -> None: ...

    async def get_client_info(self) -> OAuthClientInformationFull | None: ...

    async def set_client_info(
        self,
        client_info: OAuthClientInformationFull,
    ) -> None: ...


class LocalFileMCPTokenStorage:
    """Persist OAuth tokens/client registration in one private local file."""

    def __init__(self, directory: Path) -> None:
        """Configure a repository-relative or operator-selected private path."""

        self._directory = directory
        self._path = directory / "oauth_state.json"

    @property
    def path(self) -> Path:
        """Return the state-file path without reading its contents."""

        return self._path

    def is_configured(self) -> bool:
        """Check for token state without returning or logging token content."""

        try:
            tokens = self._read_state().get("tokens")
        except MCPAuthorizationRequiredError:
            return False
        return isinstance(tokens, dict) and bool(tokens.get("access_token"))

    async def get_tokens(self) -> OAuthToken | None:
        """Load tokens and preserve their original expiration horizon."""

        payload = self._read_state()
        raw = payload.get("tokens")
        if not isinstance(raw, dict):
            return None
        try:
            token = OAuthToken.model_validate(raw)
        except ValidationError:
            raise MCPAuthorizationRequiredError(
                "MCP OAuth state is invalid; authorization required"
            ) from None
        stored_at = payload.get("tokens_stored_at")
        if token.expires_in is not None and isinstance(stored_at, int | float):
            remaining = max(int(token.expires_in - (time.time() - stored_at)), 0)
            token = token.model_copy(update={"expires_in": remaining})
        return token

    async def set_tokens(self, tokens: OAuthToken) -> None:
        """Atomically persist tokens with owner-only permissions."""

        state = self._read_state()
        state["tokens"] = tokens.model_dump(mode="json", exclude_none=True)
        state["tokens_stored_at"] = time.time()
        self._write_state(state)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        """Load dynamic OAuth client registration, if one was issued."""

        payload = self._read_state()
        raw = payload.get("client_info")
        if not isinstance(raw, dict):
            return None
        try:
            return OAuthClientInformationFull.model_validate(raw)
        except ValidationError:
            raise MCPAuthorizationRequiredError(
                "MCP OAuth state is invalid; authorization required"
            ) from None

    async def set_client_info(
        self,
        client_info: OAuthClientInformationFull,
    ) -> None:
        """Atomically persist dynamic client registration metadata."""

        state = self._read_state()
        state["client_info"] = client_info.model_dump(
            mode="json",
            exclude_none=True,
        )
        self._write_state(state)

    def _read_state(self) -> dict[str, object]:
        if not self._path.exists():
            return {}
        try:
            decoded = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise MCPAuthorizationRequiredError(
                "MCP OAuth state is unavailable; authorization required"
            ) from None
        if not isinstance(decoded, dict):
            raise MCPAuthorizationRequiredError(
                "MCP OAuth state is invalid; authorization required"
            )
        return dict(decoded)

    def _write_state(self, value: Mapping[str, object]) -> None:
        self._directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._directory, 0o700)
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        temporary_name: str | None = None
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._directory,
                prefix=".oauth_state.",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                os.chmod(temporary.name, 0o600)
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, self._path)
            os.chmod(self._path, 0o600)
        except OSError:
            if temporary_name is not None:
                try:
                    Path(temporary_name).unlink(missing_ok=True)
                except OSError:
                    pass
            raise MCPTransportError("MCP OAuth state could not be persisted") from None


class StreamableHTTPMCPTransport:
    """Official MCP SDK client using Streamable HTTP and OAuth 2.1."""

    def __init__(
        self,
        *,
        url: str,
        token_storage: MCPTokenStorage,
        redirect_uri: str,
        redirect_handler: Callable[[str], Awaitable[None]] | None = None,
        callback_handler: Callable[[], Awaitable[tuple[str, str | None]]] | None = None,
        interactive_auth: bool = False,
        timeout_seconds: float = 60.0,
        trust_environment: bool = False,
        user_agent: str = "DeepInsight/0.1",
        client_name: str = "DeepInsight Research Data",
    ) -> None:
        """Configure one direct official-SDK remote MCP connection."""

        parsed_url = urlsplit(url)
        parsed_redirect = urlsplit(redirect_uri)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ValueError("MCP URL must be an absolute HTTPS URL")
        if parsed_redirect.scheme not in {"http", "https"}:
            raise ValueError("MCP OAuth redirect URI must use HTTP or HTTPS")
        if parsed_redirect.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("MCP OAuth redirect URI must use a loopback host")
        if timeout_seconds <= 0:
            raise ValueError("MCP timeout must be positive")
        if interactive_auth and (redirect_handler is None or callback_handler is None):
            raise ValueError(
                "interactive MCP OAuth requires redirect and callback handlers"
            )
        self._url = url
        self._token_storage = token_storage
        self._redirect_uri = redirect_uri
        self._redirect_handler = redirect_handler
        self._callback_handler = callback_handler
        self._interactive_auth = interactive_auth
        self._timeout_seconds = timeout_seconds
        self._trust_environment = trust_environment
        self._user_agent = user_agent
        self._client_name = client_name
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def initialize(self) -> None:
        """Open HTTP/session contexts and perform the MCP initialize handshake."""

        if self._session is not None:
            raise MCPInitializationError("MCP transport is already initialized")
        if (
            not self._interactive_auth
            and await self._token_storage.get_tokens() is None
        ):
            raise MCPAuthorizationRequiredError("Stocktwits MCP authorization required")
        redirect_handler = self._redirect_handler or _authorization_required_redirect
        callback_handler = self._callback_handler or _authorization_required_callback
        oauth = OAuthClientProvider(
            server_url=self._url,
            client_metadata=OAuthClientMetadata(
                client_name=self._client_name,
                redirect_uris=[AnyUrl(self._redirect_uri)],
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                token_endpoint_auth_method="none",
            ),
            storage=self._token_storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
            timeout=self._timeout_seconds,
        )
        stack = AsyncExitStack()
        try:
            client = await stack.enter_async_context(
                httpx.AsyncClient(
                    auth=oauth,
                    follow_redirects=True,
                    timeout=self._timeout_seconds,
                    headers={"User-Agent": self._user_agent},
                    trust_env=self._trust_environment,
                )
            )
            read, write, _ = await stack.enter_async_context(
                streamable_http_client(self._url, http_client=client)
            )
            session = await stack.enter_async_context(
                ClientSession(
                    read,
                    write,
                    read_timeout_seconds=timedelta(seconds=self._timeout_seconds),
                )
            )
            await session.initialize()
        except Exception as exc:
            await stack.aclose()
            if _contains_auth_failure(exc):
                raise MCPAuthorizationRequiredError(
                    "Stocktwits MCP authorization required"
                ) from None
            error_types = ",".join(sorted(_exception_type_names(exc)))
            error_origins = ",".join(sorted(_exception_origins(exc)))
            error_codes = ",".join(sorted(_mcp_error_codes(exc))) or "none"
            raise MCPInitializationError(
                "MCP initialization failed "
                f"({error_types}; {error_origins}; mcp_codes={error_codes})"
            ) from None
        self._stack = stack
        self._session = session

    async def list_tools(self) -> tuple[str, ...]:
        """Return all paginated tool names from the active MCP session."""

        session = self._require_session()
        names: list[str] = []
        cursor: str | None = None
        try:
            while True:
                result = await session.list_tools(cursor=cursor)
                names.extend(tool.name for tool in result.tools)
                cursor = result.nextCursor
                if cursor is None:
                    return tuple(names)
        except Exception:
            raise MCPTransportError("MCP tool discovery failed") from None

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> MCPToolResult:
        """Call one tool and reduce the SDK result to a JSON object."""

        session = self._require_session()
        try:
            result = await session.call_tool(
                tool_name,
                arguments,
                read_timeout_seconds=timedelta(seconds=self._timeout_seconds),
            )
        except Exception:
            raise MCPToolError("MCP tool call failed") from None
        if result.isError:
            raise MCPToolError("MCP tool returned an error")
        raw: object = result.structuredContent
        if raw is None:
            raw = _decode_text_content(result)
        return MCPToolResult(data=_json_mapping(raw))

    async def close(self) -> None:
        """Close all official SDK and HTTP contexts without exposing state."""

        stack = self._stack
        self._stack = None
        self._session = None
        if stack is None:
            return
        try:
            await stack.aclose()
        except Exception:
            raise MCPTransportError("MCP transport close failed") from None

    def _require_session(self) -> ClientSession:
        if self._session is None:
            raise MCPInitializationError("MCP transport is not initialized")
        return self._session


class FakeMCPTransport:
    """Deterministic offline MCP transport for Provider contract tests."""

    def __init__(
        self,
        *,
        tools: tuple[str, ...],
        results: Mapping[str, Mapping[str, object]],
        initialize_error: MCPTransportError | None = None,
        call_errors: Mapping[str, MCPTransportError] | None = None,
    ) -> None:
        self._tools = tools
        self._results = results
        self._initialize_error = initialize_error
        self._call_errors = call_errors or {}
        self.initialized = False
        self.closed = False
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def initialize(self) -> None:
        if self._initialize_error is not None:
            raise self._initialize_error
        self.initialized = True

    async def list_tools(self) -> tuple[str, ...]:
        if not self.initialized:
            raise MCPInitializationError("fake MCP transport is not initialized")
        return self._tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> MCPToolResult:
        self.calls.append((tool_name, dict(arguments)))
        if tool_name in self._call_errors:
            raise self._call_errors[tool_name]
        if tool_name not in self._results:
            raise MCPToolError("fake MCP tool has no configured result")
        return MCPToolResult(data=self._results[tool_name])

    async def close(self) -> None:
        self.closed = True


async def _authorization_required_redirect(auth_url: str) -> None:
    del auth_url
    raise MCPAuthorizationRequiredError("Stocktwits MCP authorization required")


async def _authorization_required_callback() -> tuple[str, str | None]:
    raise MCPAuthorizationRequiredError("Stocktwits MCP authorization required")


def _decode_text_content(result: types.CallToolResult) -> object:
    text_blocks = [
        block.text for block in result.content if isinstance(block, types.TextContent)
    ]
    if len(text_blocks) != 1:
        raise MCPToolError("MCP tool result has no unique JSON object")
    try:
        return json.loads(text_blocks[0])
    except ValueError:
        raise MCPToolError("MCP tool result is not valid JSON") from None


def _json_mapping(value: object) -> Mapping[str, object]:
    try:
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
        decoded = json.loads(encoded)
    except (TypeError, ValueError):
        raise MCPToolError("MCP tool result is not JSON-compatible") from None
    if not isinstance(decoded, dict):
        raise MCPToolError("MCP tool result must be an object")
    return dict(decoded)


def _contains_auth_failure(error: BaseException) -> bool:
    auth_types = (
        MCPAuthorizationRequiredError,
        OAuthFlowError,
        OAuthRegistrationError,
        OAuthTokenError,
    )
    if isinstance(error, auth_types):
        return True
    if isinstance(error, BaseExceptionGroup):
        return any(_contains_auth_failure(item) for item in error.exceptions)
    return False


def _exception_type_names(error: BaseException) -> set[str]:
    """Return only exception class names for credential-safe diagnostics."""

    names = {type(error).__name__}
    if isinstance(error, BaseExceptionGroup):
        for item in error.exceptions:
            names.update(_exception_type_names(item))
    return names


def _exception_origins(error: BaseException) -> set[str]:
    """Return safe module/function origins without exception messages."""

    frames = traceback.extract_tb(error.__traceback__)
    origins = (
        {f"{Path(frames[-1].filename).name}:{frames[-1].name}"} if frames else set()
    )
    if isinstance(error, BaseExceptionGroup):
        for item in error.exceptions:
            origins.update(_exception_origins(item))
    return origins


def _mcp_error_codes(error: BaseException) -> set[str]:
    """Return protocol error codes without server messages or payloads."""

    codes = {str(error.error.code)} if isinstance(error, McpError) else set()
    if isinstance(error, BaseExceptionGroup):
        for item in error.exceptions:
            codes.update(_mcp_error_codes(item))
    return codes
