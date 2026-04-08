"""Environment configuration helper for secure credential management."""
import os
import re
from typing import Any, Dict


def resolve_env_vars(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively resolve environment variables in configuration.
    Supports ${VAR_NAME} syntax with optional defaults: ${VAR_NAME:default_value}
    """
    if isinstance(config, dict):
        return {k: resolve_env_vars(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [resolve_env_vars(item) for item in config]
    elif isinstance(config, str):
        return _resolve_env_string(config)
    else:
        return config


def _resolve_env_string(value: str) -> str:
    """Resolve environment variables in a string."""
    pattern = r'\$\{([^}]+)\}'
    
    def replace_var(match):
        var_expr = match.group(1)
        if ':' in var_expr:
            var_name, default = var_expr.split(':', 1)
        else:
            var_name, default = var_expr, ''
        
        return os.getenv(var_name.strip(), default)
    
    return re.sub(pattern, replace_var, value)


def validate_required_env_vars(required_vars: list[str]) -> None:
    """Validate that required environment variables are set."""
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")