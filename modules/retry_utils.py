# modules/retry_utils.py
"""
Retry utilities for handling transient network failures.
"""
import time
from typing import Callable, Optional, Type, Tuple
from functools import wraps
from loguru import logger
import httpx


class RetryConfig:
    """Configuration for retry behavior"""
    def __init__(self,
                 max_attempts: int = 3,
                 base_delay: float = 1.0,
                 max_delay: float = 30.0,
                 exponential_base: float = 2.0):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number using exponential backoff"""
        delay = self.base_delay * (self.exponential_base ** (attempt - 1))
        return min(delay, self.max_delay)


# Network errors that should be retried
RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
    ConnectionError,
    TimeoutError,
)

# HTTP status codes that should be retried
RETRYABLE_STATUS_CODES = (
    408,  # Request Timeout
    429,  # Too Many Requests
    500,  # Internal Server Error
    502,  # Bad Gateway
    503,  # Service Unavailable
    504,  # Gateway Timeout
)


def is_retryable_error(error: Exception) -> bool:
    """
    Determine if an error should trigger a retry.

    Args:
        error: The exception that occurred

    Returns:
        True if the error is retryable (transient network issue)
    """
    # Check if it's a known retryable exception
    if isinstance(error, RETRYABLE_EXCEPTIONS):
        return True

    # Check if it's an HTTP error with retryable status
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in RETRYABLE_STATUS_CODES

    # Check error message for network-related keywords
    error_msg = str(error).lower()
    retryable_keywords = [
        'timeout',
        'connection',
        'network',
        'temporary',
        'unavailable',
        'refused',
        'reset'
    ]
    return any(keyword in error_msg for keyword in retryable_keywords)


def is_non_retryable_error(error: Exception) -> bool:
    """
    Determine if an error should NOT be retried.

    Args:
        error: The exception that occurred

    Returns:
        True if the error is permanent (authentication, file not found, etc.)
    """
    # Authentication errors - don't retry
    if isinstance(error, httpx.HTTPStatusError):
        if error.response.status_code in (401, 403):
            return True

    # Client errors (4xx except retryable ones) - don't retry
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if 400 <= status < 500 and status not in RETRYABLE_STATUS_CODES:
            return True

    # File/path errors - don't retry
    error_msg = str(error).lower()
    non_retryable_keywords = [
        'not found',
        'permission denied',
        'unauthorized',
        'forbidden',
        'invalid credentials',
        'authentication failed'
    ]
    return any(keyword in error_msg for keyword in non_retryable_keywords)


def retry_on_network_error(config: Optional[RetryConfig] = None):
    """
    Decorator to retry a function on network errors with exponential backoff.

    Args:
        config: RetryConfig instance, or None to use defaults

    Example:
        @retry_on_network_error(RetryConfig(max_attempts=5))
        def upload_file(file_path):
            # Upload logic that might fail
            pass
    """
    if config is None:
        config = RetryConfig()

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(1, config.max_attempts + 1):
                try:
                    return func(*args, **kwargs)

                except Exception as e:
                    last_exception = e

                    # Don't retry if it's a permanent error
                    if is_non_retryable_error(e):
                        logger.warning(f"{func.__name__}: Non-retryable error: {e}")
                        raise

                    # Don't retry if it's not a network error
                    if not is_retryable_error(e):
                        logger.warning(f"{func.__name__}: Not a retryable error: {e}")
                        raise

                    # Calculate delay and retry
                    if attempt < config.max_attempts:
                        delay = config.get_delay(attempt)
                        logger.info(
                            f"{func.__name__}: Attempt {attempt}/{config.max_attempts} failed: {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"{func.__name__}: All {config.max_attempts} attempts failed. "
                            f"Last error: {e}"
                        )

            # If we get here, all attempts failed
            raise last_exception

        return wrapper
    return decorator


class RetryableHTTPClient:
    """
    Wrapper around httpx.Client that automatically retries network errors.
    """

    def __init__(self, client: httpx.Client, config: Optional[RetryConfig] = None):
        self.client = client
        self.config = config or RetryConfig()

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """
        Make an HTTP request with automatic retry on network errors.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            **kwargs: Additional arguments to pass to httpx.Client.request()

        Returns:
            httpx.Response object

        Raises:
            Exception: If all retry attempts fail
        """
        @retry_on_network_error(self.config)
        def _make_request():
            return self.client.request(method, url, **kwargs)

        return _make_request()

    def get(self, url: str, **kwargs) -> httpx.Response:
        """GET request with retry"""
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        """POST request with retry"""
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs) -> httpx.Response:
        """PUT request with retry"""
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs) -> httpx.Response:
        """DELETE request with retry"""
        return self.request("DELETE", url, **kwargs)

    def close(self):
        """Close the underlying HTTP client"""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
