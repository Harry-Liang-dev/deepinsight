"""Provider adapters and provider-independent ingestion contracts."""

from src.adapters.base import (
    BaseProviderAdapter,
    ProviderAdapterError,
    ProviderRecord,
    ProviderUnavailableError,
)
from src.adapters.fmp import FinancialModelingPrepAdapter, FMPProviderSnapshot
from src.adapters.mcp import (
    FakeMCPTransport,
    LocalFileMCPTokenStorage,
    MCPAuthorizationRequiredError,
    MCPInitializationError,
    MCPTokenStorage,
    MCPToolError,
    MCPToolResult,
    MCPTransport,
    MCPTransportError,
    StreamableHTTPMCPTransport,
)
from src.adapters.providers import (
    AlpacaAdapter,
    BloombergLicensedAdapter,
    CNINFOAdapter,
    FakeProviderAdapter,
    FREDAdapter,
    FREDProviderRequestError,
    HKEXNewsAdapter,
    LSEGLicensedAdapter,
    SECEDGARAdapter,
    WindAdapter,
    XSearchAdapter,
)
from src.adapters.stocktwits import StocktwitsSentimentProvider
from src.adapters.stocktwits_runtime import (
    build_stocktwits_mcp_transport,
    build_stocktwits_provider,
    stocktwits_authorization_configured,
)

__all__ = [
    "AlpacaAdapter",
    "BaseProviderAdapter",
    "BloombergLicensedAdapter",
    "CNINFOAdapter",
    "FakeProviderAdapter",
    "FMPProviderSnapshot",
    "FinancialModelingPrepAdapter",
    "FREDAdapter",
    "FREDProviderRequestError",
    "FakeMCPTransport",
    "HKEXNewsAdapter",
    "LSEGLicensedAdapter",
    "LocalFileMCPTokenStorage",
    "MCPAuthorizationRequiredError",
    "MCPInitializationError",
    "MCPTokenStorage",
    "MCPToolError",
    "MCPToolResult",
    "MCPTransport",
    "MCPTransportError",
    "ProviderAdapterError",
    "ProviderRecord",
    "ProviderUnavailableError",
    "SECEDGARAdapter",
    "StocktwitsSentimentProvider",
    "StreamableHTTPMCPTransport",
    "WindAdapter",
    "XSearchAdapter",
    "build_stocktwits_mcp_transport",
    "build_stocktwits_provider",
    "stocktwits_authorization_configured",
]
