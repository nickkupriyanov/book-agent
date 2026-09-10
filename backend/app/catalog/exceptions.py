class CatalogError(Exception):
    """Base error raised at the external catalog boundary."""


class CatalogPayloadError(CatalogError):
    """The provider returned a response that cannot be normalized."""


class CatalogUnavailableError(CatalogError):
    """The external catalog cannot serve this request safely."""
