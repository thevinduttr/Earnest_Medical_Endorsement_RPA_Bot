"""Centralized error handling utilities."""
import logging
from typing import Optional, Type, Union
from functools import wraps


class AutomationError(Exception):
    """Base exception for automation-related errors."""
    pass


class ConfigurationError(AutomationError):
    """Raised when configuration is invalid or missing."""
    pass


class ValidationError(AutomationError):
    """Raised when data validation fails."""
    pass


class NetworkError(AutomationError):
    """Raised when network operations fail."""
    pass


def handle_exceptions(
    logger: Optional[logging.Logger] = None,
    reraise: bool = True,
    default_return=None
):
    """Decorator for consistent exception handling."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except (ConfigurationError, ValidationError) as e:
                if logger:
                    logger.error(f"Configuration/Validation error in {func.__name__}: {e}")
                if reraise:
                    raise
                return default_return
            except NetworkError as e:
                if logger:
                    logger.error(f"Network error in {func.__name__}: {e}")
                if reraise:
                    raise
                return default_return
            except Exception as e:
                if logger:
                    logger.error(f"Unexpected error in {func.__name__}: {e}")
                if reraise:
                    raise
                return default_return
        return wrapper
    return decorator


def safe_execute(func, *args, logger: Optional[logging.Logger] = None, **kwargs):
    """Safely execute a function with error logging."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if logger:
            logger.error(f"Error executing {func.__name__}: {e}")
        raise