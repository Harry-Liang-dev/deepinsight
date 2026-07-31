"""Stable API exceptions and unified FastAPI error handlers."""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.schemas import ApiErrorResponse
from src.models.types import JsonObject, JsonValue
from src.schemas.common import ErrorInfo


class ApiError(RuntimeError):
    """A safe application error with an explicit HTTP mapping."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        retryable: bool = False,
        details: JsonObject | None = None,
    ) -> None:
        """Create one safe HTTP-facing application error."""

        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details


def not_found(code: str, message: str) -> ApiError:
    """Return a standard not-found API error."""

    return ApiError(code=code, message=message, status_code=404)


def service_unavailable(message: str) -> ApiError:
    """Return a retryable service-unavailable API error."""

    return ApiError(
        code="service_unavailable",
        message=message,
        status_code=503,
        retryable=True,
    )


def phase_two_not_implemented() -> ApiError:
    """Return the stable Phase Two placeholder error."""

    return ApiError(
        code="phase_two_not_implemented",
        message="This Phase Two capability is not implemented in Phase One.",
        status_code=501,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register unified handlers without exposing internal exception details."""

    app.add_exception_handler(ApiError, _handle_api_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)
    app.add_exception_handler(Exception, _handle_internal_error)


async def _handle_api_error(request: Request, exc: Exception) -> JSONResponse:
    del request
    error = cast(ApiError, exc)
    return _error_response(
        error.status_code,
        ErrorInfo(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            details=error.details,
        ),
    )


async def _handle_validation_error(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    del request
    validation_error = cast(RequestValidationError, exc)
    errors: list[JsonValue] = [
        {
            "location": ".".join(str(item) for item in error["loc"]),
            "message": str(error["msg"]),
            "type": str(error["type"]),
        }
        for error in validation_error.errors()
    ]
    return _error_response(
        422,
        ErrorInfo(
            code="validation_error",
            message="Request validation failed.",
            details={"errors": errors},
        ),
    )


async def _handle_http_error(request: Request, exc: Exception) -> JSONResponse:
    del request
    http_error = cast(StarletteHTTPException, exc)
    code = "http_not_found" if http_error.status_code == 404 else "http_error"
    message = (
        "The requested endpoint was not found."
        if http_error.status_code == 404
        else "The HTTP request could not be completed."
    )
    return _error_response(
        http_error.status_code,
        ErrorInfo(code=code, message=message),
    )


async def _handle_internal_error(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    del request, exc
    return _error_response(
        500,
        ErrorInfo(
            code="internal_error",
            message="The service could not complete the request.",
            retryable=True,
        ),
    )


def _error_response(status_code: int, error: ErrorInfo) -> JSONResponse:
    body = ApiErrorResponse(error=error)
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
    )
