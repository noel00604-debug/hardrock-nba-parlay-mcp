"""Shared exception types (foundation). Every module raises these for user-facing failures."""

from __future__ import annotations


class ServiceError(Exception):
    """A user-facing failure with reason codes from docs/ARCHITECTURE.md section 7."""

    def __init__(
        self, message: str, reason_codes: list[str] | None = None, detail: str | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.reason_codes = list(reason_codes or [])
        self.detail = detail

    def to_dict(self) -> dict[str, object]:
        return {"error": self.message, "reason_codes": self.reason_codes, "detail": self.detail}


class NotFound(ServiceError):
    def __init__(self, message: str = "not found", detail: str | None = None) -> None:
        super().__init__(message, ["NOT_FOUND"], detail)


class Forbidden(ServiceError):
    def __init__(self, message: str = "forbidden", detail: str | None = None) -> None:
        super().__init__(message, ["FORBIDDEN"], detail)


class Unauthenticated(ServiceError):
    def __init__(self, message: str = "authentication required", detail: str | None = None) -> None:
        super().__init__(message, ["UNAUTHENTICATED"], detail)


class InvalidInput(ServiceError):
    def __init__(
        self, message: str, reason_codes: list[str] | None = None, detail: str | None = None
    ) -> None:
        super().__init__(message, reason_codes or ["INVALID_INPUT"], detail)


class ProviderError(ServiceError):
    """Raised by data providers. `retry_after` is seconds when the provider asked us to back off."""

    def __init__(
        self,
        message: str,
        reason_codes: list[str] | None = None,
        detail: str | None = None,
        retry_after: float | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, reason_codes or ["PROVIDER_ERROR"], detail)
        self.retry_after = retry_after
        self.status_code = status_code
