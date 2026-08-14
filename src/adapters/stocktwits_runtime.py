"""Production composition helpers for the official Stocktwits remote MCP."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from src.adapters.mcp import LocalFileMCPTokenStorage, StreamableHTTPMCPTransport
from src.adapters.stocktwits import StocktwitsSentimentProvider
from src.core.settings import ProviderSettings


def build_stocktwits_mcp_transport(
    settings: ProviderSettings,
    *,
    interactive_auth: bool = False,
    timeout_seconds: float | None = None,
    redirect_handler: Callable[[str], Awaitable[None]] | None = None,
    callback_handler: Callable[[], Awaitable[tuple[str, str | None]]] | None = None,
) -> StreamableHTTPMCPTransport:
    """Build the direct official-SDK transport from validated Settings."""

    return StreamableHTTPMCPTransport(
        url=settings.stocktwits_mcp_url,
        token_storage=LocalFileMCPTokenStorage(settings.stocktwits_mcp_token_store),
        redirect_uri=settings.stocktwits_mcp_redirect_uri,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
        interactive_auth=interactive_auth,
        timeout_seconds=(
            settings.stocktwits_mcp_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        ),
        trust_environment=settings.stocktwits_mcp_trust_env,
    )


def build_stocktwits_provider(
    settings: ProviderSettings,
) -> StocktwitsSentimentProvider:
    """Build the real runtime Provider; never substitute a fake transport."""

    return StocktwitsSentimentProvider(
        transport=build_stocktwits_mcp_transport(settings),
        history_zoom=settings.stocktwits_history_zoom,
        message_limit=settings.stocktwits_message_limit,
        max_message_pages=settings.stocktwits_max_message_pages,
    )


def stocktwits_authorization_configured(settings: ProviderSettings) -> bool:
    """Inspect only token-state presence without loading or exposing content."""

    return LocalFileMCPTokenStorage(settings.stocktwits_mcp_token_store).is_configured()
