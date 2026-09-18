"""EIP-1 Structured Error Model.

Provides a stable, machine-readable error taxonomy for the
ecosystem boundary. Maps from existing Zarya errors where
possible rather than inventing a parallel taxonomy.

Error response shape:
{
    "error": {
        "code": "ERROR_CODE",
        "message": "Human-readable description",
        "detail": { ... }   // optional, error-specific
    }
}
"""


class EcosystemErrorCode:
    """Stable error codes for the ecosystem protocol.

    These codes are part of the external contract and should
    not change between minor versions.
    """
    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_PROTOCOL = "UNSUPPORTED_PROTOCOL"
    CAPABILITY_NOT_ADVERTISED = "CAPABILITY_NOT_ADVERTISED"
    OPERATION_NOT_SUPPORTED = "OPERATION_NOT_SUPPORTED"
    UNAUTHORIZED = "UNAUTHORIZED"
    BUSY = "BUSY"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_STATE = "INVALID_STATE"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
    UNKNOWN = "UNKNOWN"


# HTTP status code mapping for each error
_ERROR_HTTP_STATUS = {
    EcosystemErrorCode.INVALID_REQUEST: 400,
    EcosystemErrorCode.UNSUPPORTED_PROTOCOL: 400,
    EcosystemErrorCode.CAPABILITY_NOT_ADVERTISED: 404,
    EcosystemErrorCode.OPERATION_NOT_SUPPORTED: 404,
    EcosystemErrorCode.UNAUTHORIZED: 401,
    EcosystemErrorCode.BUSY: 503,
    EcosystemErrorCode.UNAVAILABLE: 503,
    EcosystemErrorCode.INVALID_STATE: 409,
    EcosystemErrorCode.EXECUTION_FAILED: 500,
    EcosystemErrorCode.VERIFICATION_FAILED: 500,
    EcosystemErrorCode.TOOL_NOT_ALLOWED: 403,
    EcosystemErrorCode.UNKNOWN: 500,
}


def make_error(code: str, message: str, detail: dict = None) -> dict:
    """Build a structured error response dict.

    Args:
        code: An EcosystemErrorCode value.
        message: Human-readable error description.
        detail: Optional additional error context.

    Returns:
        A dict with the standard error envelope.
    """
    error = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if detail is not None:
        error["error"]["detail"] = detail
    return error


def get_http_status(code: str) -> int:
    """Map an ecosystem error code to an HTTP status code."""
    return _ERROR_HTTP_STATUS.get(code, 500)


def from_tool_error(tool_error_message: str) -> dict:
    """Map an existing Zarya ToolError to an ecosystem error.

    This preserves the existing error information while wrapping
    it in the ecosystem error envelope.
    """
    return make_error(
        EcosystemErrorCode.EXECUTION_FAILED,
        "Tool execution failed",
        {"tool_error": tool_error_message},
    )
