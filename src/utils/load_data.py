from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import json

import yaml


def _resolve_project_path(path: str | Path) -> Path:
    """Resolve a project-relative path and prevent accidental traversal outside workspace."""
    resolved = Path(path).resolve()
    workspace_root = Path.cwd().resolve()
    if not str(resolved).startswith(str(workspace_root)):
        raise ValueError(f"Path outside project directory: {resolved}")
    return resolved


def load_yaml_file(path: str | Path) -> Dict[str, Any]:
    file_path = _resolve_project_path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"YAML not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def load_section_from_yaml(path: str | Path, section: str) -> Dict[str, Any]:
    data = load_yaml_file(path)
    value = data.get(section, {})
    if not isinstance(value, dict):
        return {}
    return value


def load_json_file(path: str | Path) -> Dict[str, Any]:
    file_path = _resolve_project_path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"JSON not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)

    if isinstance(data, dict):
        return data
    raise ValueError(f"Expected JSON object in {file_path}, got {type(data).__name__}")
