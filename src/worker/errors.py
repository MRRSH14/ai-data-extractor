from shared import ErrorCode


class NonRetryableProcessingError(Exception):
    """Raised for deterministic payload/contract issues that should not retry."""


def non_retryable(code: str, message: str) -> NonRetryableProcessingError:
    return NonRetryableProcessingError(f"[{code}] {message}")


def retryable_error_message(exc: Exception) -> str:
    exc_type = type(exc).__name__
    detail = str(exc).strip() or "transient worker failure"
    return f"[{ErrorCode.WORKER_TRANSIENT}:{exc_type}] {detail}"
