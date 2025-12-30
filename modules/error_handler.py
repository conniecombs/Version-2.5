# modules/error_handler.py
"""
Centralized error handling framework for consistent error management.
"""
import queue
import traceback
from enum import Enum
from typing import Optional, Callable
from datetime import datetime
from loguru import logger


class ErrorSeverity(Enum):
    """Error severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorContext:
    """Context information for errors"""
    def __init__(self, operation: str, file_path: Optional[str] = None,
                 service: Optional[str] = None, details: Optional[dict] = None):
        self.operation = operation
        self.file_path = file_path
        self.service = service
        self.details = details or {}
        self.timestamp = datetime.now()

    def __str__(self):
        parts = [f"Operation: {self.operation}"]
        if self.file_path:
            parts.append(f"File: {self.file_path}")
        if self.service:
            parts.append(f"Service: {self.service}")
        if self.details:
            parts.append(f"Details: {self.details}")
        return " | ".join(parts)


class UserNotification:
    """User-facing notification"""
    def __init__(self, title: str, message: str, severity: ErrorSeverity,
                 details: str = "", show_details_button: bool = False):
        self.title = title
        self.message = message
        self.severity = severity
        self.details = details
        self.show_details_button = show_details_button
        self.timestamp = datetime.now()


class ErrorHandler:
    """
    Centralized error handler providing consistent error logging,
    user notifications, and error tracking.
    """

    def __init__(self):
        self.notification_queue = queue.Queue()
        self.error_count = 0
        self.warning_count = 0
        self.custom_handlers = {}

    def handle(self,
               error: Exception,
               context: ErrorContext,
               severity: ErrorSeverity = ErrorSeverity.ERROR,
               user_message: Optional[str] = None,
               notify_user: bool = True,
               log_traceback: bool = True) -> None:
        """
        Handle an error with consistent logging and user notification.

        Args:
            error: The exception that occurred
            context: Context information about where/why the error occurred
            severity: Severity level of the error
            user_message: Optional user-friendly message (auto-generated if None)
            notify_user: Whether to queue a user notification
            log_traceback: Whether to log full traceback
        """
        # Update counters
        if severity == ErrorSeverity.ERROR or severity == ErrorSeverity.CRITICAL:
            self.error_count += 1
        elif severity == ErrorSeverity.WARNING:
            self.warning_count += 1

        # Log the error
        log_msg = f"{context} | Error: {str(error)}"

        if log_traceback and severity in [ErrorSeverity.ERROR, ErrorSeverity.CRITICAL]:
            logger.exception(log_msg)
        else:
            log_level = severity.value
            getattr(logger, log_level)(log_msg)

        # Generate user notification if requested
        if notify_user and severity in [ErrorSeverity.ERROR, ErrorSeverity.CRITICAL, ErrorSeverity.WARNING]:
            self._queue_user_notification(error, context, severity, user_message)

        # Call custom handler if registered
        handler_key = f"{context.operation}:{severity.value}"
        if handler_key in self.custom_handlers:
            self.custom_handlers[handler_key](error, context)

    def _queue_user_notification(self,
                                  error: Exception,
                                  context: ErrorContext,
                                  severity: ErrorSeverity,
                                  custom_message: Optional[str]) -> None:
        """Queue a user notification"""

        # Generate user-friendly message
        if custom_message:
            message = custom_message
        else:
            message = self._generate_user_message(error, context)

        # Generate title based on context
        title = self._generate_title(context, severity)

        # Technical details for "show details" button
        details = self._generate_technical_details(error, context)

        notification = UserNotification(
            title=title,
            message=message,
            severity=severity,
            details=details,
            show_details_button=True
        )

        self.notification_queue.put(notification)

    def _generate_user_message(self, error: Exception, context: ErrorContext) -> str:
        """Generate user-friendly error message"""

        # Network errors
        if "Connection" in str(error) or "Timeout" in str(error):
            return "Network connection failed. Please check your internet connection and try again."

        # Authentication errors
        if "401" in str(error) or "Unauthorized" in str(error) or "credentials" in str(error).lower():
            return "Authentication failed. Please check your credentials in Settings."

        # File errors
        if context.file_path:
            if "Permission" in str(error):
                return f"Cannot access file: {context.file_path}\nPermission denied."
            elif "Not found" in str(error):
                return f"File not found: {context.file_path}"
            else:
                return f"Error processing file: {context.file_path}\n{str(error)}"

        # Service-specific errors
        if context.service:
            return f"{context.service} error: {str(error)}"

        # Generic fallback
        return f"{context.operation} failed: {str(error)}"

    def _generate_title(self, context: ErrorContext, severity: ErrorSeverity) -> str:
        """Generate notification title"""
        if severity == ErrorSeverity.CRITICAL:
            return "Critical Error"
        elif severity == ErrorSeverity.ERROR:
            return f"{context.operation} Failed"
        elif severity == ErrorSeverity.WARNING:
            return f"{context.operation} Warning"
        else:
            return "Information"

    def _generate_technical_details(self, error: Exception, context: ErrorContext) -> str:
        """Generate technical details for debugging"""
        details = []
        details.append(f"Error Type: {type(error).__name__}")
        details.append(f"Error Message: {str(error)}")
        details.append(f"Context: {context}")
        details.append(f"Timestamp: {context.timestamp}")

        # Add traceback if available
        tb = traceback.format_exc()
        if tb and "NoneType" not in tb:
            details.append(f"\nTraceback:\n{tb}")

        return "\n".join(details)

    def register_custom_handler(self, operation: str, severity: ErrorSeverity,
                                handler: Callable) -> None:
        """
        Register a custom handler for specific operation/severity combinations.

        Args:
            operation: The operation name (from ErrorContext)
            severity: The error severity to handle
            handler: Callable that takes (error, context) as arguments
        """
        key = f"{operation}:{severity.value}"
        self.custom_handlers[key] = handler

    def get_notification(self, block: bool = False, timeout: Optional[float] = None) -> Optional[UserNotification]:
        """
        Get next user notification from queue.

        Args:
            block: Whether to block waiting for notification
            timeout: Timeout in seconds if blocking

        Returns:
            UserNotification or None if queue is empty
        """
        try:
            return self.notification_queue.get(block=block, timeout=timeout)
        except queue.Empty:
            return None

    def has_notifications(self) -> bool:
        """Check if there are pending notifications"""
        return not self.notification_queue.empty()

    def get_stats(self) -> dict:
        """Get error statistics"""
        return {
            'errors': self.error_count,
            'warnings': self.warning_count,
            'pending_notifications': self.notification_queue.qsize()
        }

    def reset_stats(self) -> None:
        """Reset error counters"""
        self.error_count = 0
        self.warning_count = 0


# Global error handler instance
_error_handler = None

def get_error_handler() -> ErrorHandler:
    """Get the global error handler instance (singleton)"""
    global _error_handler
    if _error_handler is None:
        _error_handler = ErrorHandler()
    return _error_handler


# Convenience functions for common error handling patterns

def handle_upload_error(error: Exception, file_path: str, service: str,
                       user_message: Optional[str] = None) -> None:
    """Convenience function for handling upload errors"""
    context = ErrorContext(
        operation="Upload",
        file_path=file_path,
        service=service
    )
    get_error_handler().handle(error, context, ErrorSeverity.ERROR, user_message)


def handle_network_error(error: Exception, operation: str, service: str) -> None:
    """Convenience function for handling network errors"""
    context = ErrorContext(
        operation=operation,
        service=service
    )
    get_error_handler().handle(
        error,
        context,
        ErrorSeverity.WARNING,
        user_message="Network error. The operation will be retried automatically."
    )


def handle_authentication_error(error: Exception, service: str) -> None:
    """Convenience function for handling authentication errors"""
    context = ErrorContext(
        operation="Authentication",
        service=service
    )
    get_error_handler().handle(
        error,
        context,
        ErrorSeverity.ERROR,
        user_message=f"Authentication failed for {service}. Please check your credentials in Tools > Set Credentials."
    )
