"""Provider adapters and provider-independent ingestion contracts."""

from src.adapters.base import (
    BaseProviderAdapter,
    ProviderAdapterError,
    ProviderRecord,
    ProviderUnavailableError,
)
from src.adapters.providers import (
    AlpacaAdapter,
    BloombergLicensedAdapter,
    CNINFOAdapter,
    FakeProviderAdapter,
    FREDAdapter,
    HKEXNewsAdapter,
    LSEGLicensedAdapter,
    SECEDGARAdapter,
    WindAdapter,
    XSearchAdapter,
)

__all__ = [
    "AlpacaAdapter",
    "BaseProviderAdapter",
    "BloombergLicensedAdapter",
    "CNINFOAdapter",
    "FakeProviderAdapter",
    "FREDAdapter",
    "HKEXNewsAdapter",
    "LSEGLicensedAdapter",
    "ProviderAdapterError",
    "ProviderRecord",
    "ProviderUnavailableError",
    "SECEDGARAdapter",
    "WindAdapter",
    "XSearchAdapter",
]
