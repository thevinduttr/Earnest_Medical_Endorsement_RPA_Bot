"""Type definitions for the Earnest CRM project."""
from typing import TypedDict, Protocol, Dict, Any, List, Optional
from pathlib import Path


class ActionDict(TypedDict, total=False):
    type: str
    key: str
    label: str
    value: Any
    value_col: str
    required: bool
    timeout_ms: int
    mask: bool
    validation_check: bool


class ConfigDict(TypedDict):
    paths: Dict[str, str]
    browser: Dict[str, Any]


class LoggerProtocol(Protocol):
    def info(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...
    def debug(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...


class ProcessMetrics(TypedDict):
    start_time: float
    end_time: float
    duration: float
    success: bool
    error_count: int