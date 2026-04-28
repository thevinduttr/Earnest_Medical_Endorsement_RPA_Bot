from __future__ import annotations
from typing import Any, Dict, Mapping, List
from pathlib import Path
import yaml
import pandas as pd

# ---------- Loaders ----------

def load_yaml_file(path: str | Path) -> Dict[str, Any]:
    p = Path(path).resolve()
    # Ensure path is within project directory
    project_root = Path.cwd().resolve()
    if not str(p).startswith(str(project_root)):
        raise ValueError(f"Path outside project directory: {p}")
    if not p.exists():
        raise FileNotFoundError(f"YAML not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def load_section_from_yaml(path: str | Path, section: str) -> Dict[str, Any]:
    """
    Return the mapping stored under a top-level section name in a single YAML file.
    Example: section='login' reads YAML['login'].
    """
    cfg = load_yaml_file(path)
    data = cfg.get(section, {})
    if not isinstance(data, dict):
        return {}
    return data

def load_selectors_from_yaml(path: str | Path, section: str = "selectors") -> Dict[str, Any]:
    """
    Return the mapping under the given top-level section. Default 'selectors'.
    You can call: load_selectors_from_yaml(file, section='login')
    """
    return load_section_from_yaml(path, section)

def load_json_df(path: str | Path) -> pd.DataFrame:
    """Load a JSON array of objects into a DataFrame (each object = one row)."""
    p = Path(path).resolve()
    # Ensure path is within project directory
    project_root = Path.cwd().resolve()
    if not str(p).startswith(str(project_root)):
        raise ValueError(f"Path outside project directory: {p}")
    if not p.exists():
        raise FileNotFoundError(f"JSON not found: {p}")
    df = pd.read_json(p)
    if not isinstance(df, pd.DataFrame):
        raise ValueError("JSON did not produce a DataFrame")
    if df.shape[0] == 0:
        raise ValueError("Provided JSON produced an empty DataFrame")
    return df

# ---------- YAML access ----------

def get_value(mapping: Mapping[str, Any], key: str, default: Any = None) -> Any:
    """Fetch a value by dot-path from a nested mapping. e.g., get_value(cfg, 'paths.base_url')."""
    if not key:
        return default
    cur: Any = mapping
    for part in key.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur

# alias per your preference
get_yml_value = get_value

# ---------- DataFrame helpers ----------

def df_first_value(df: pd.DataFrame, col: str, default: Any = None) -> Any:
    """Return first-row value of a column (normalizes NaN to default)."""
    if col not in df.columns or df.shape[0] == 0:
        return default
    val = df.iloc[0][col]
    if pd.isna(val):
        return default
    return val

# ---------- Validators (centralized) ----------

def validate_config_yaml(cfg: Mapping[str, Any], required_keys: List[str]) -> None:
    """Validate required keys exist in YAML (dot-paths)."""
    missing = [k for k in required_keys if get_value(cfg, k, None) in (None, "")]
    if missing:
        raise ValueError(f"Missing required YAML keys: {', '.join(missing)}")

def validate_required_df(df: pd.DataFrame, required_cols: List[str], require_any: bool = False) -> None:
    """
    Validate required columns and values in the first row.

    - Default (require_any=False): all required_cols must exist and have non-empty values.
    - If require_any=True: at least one of required_cols must both exist and have a non-empty first-row value.
    """
    if not isinstance(required_cols, list) or len(required_cols) == 0:
        return

    # Check for missing columns (only relevant when requiring all; for require_any we still
    # need to know if none of the candidates exist at all)
    missing_cols = [c for c in required_cols if c not in df.columns]
    if not require_any and missing_cols:
        raise ValueError(f"Missing required columns in DataFrame: {', '.join(missing_cols)}")

    # Helper to detect empty/invalid first-row value
    def is_empty(col: str) -> bool:
        if col not in df.columns or df.shape[0] == 0:
            return True
        val = df.iloc[0][col]
        return pd.isna(val) or str(val).strip() == ""

    if require_any:
        # At least one of the required_cols must be present AND non-empty in first row
        valid_cols = [c for c in required_cols if (c in df.columns and not is_empty(c))]
        if not valid_cols:
            # Provide helpful message: list which of the candidates are missing vs empty
            existing = [c for c in required_cols if c in df.columns]
            if not existing:
                raise ValueError(f"None of the required candidate columns found. Expected one of: {', '.join(required_cols)}")
            else:
                raise ValueError(f"None of the candidate columns have a value in the first row: {', '.join(existing)}")
        return

    # Default (require all): ensure none of the required columns are empty in first row
    empty_cols = [c for c in required_cols if is_empty(c)]
    if empty_cols:
        raise ValueError(f"Empty/invalid values in first row for: {', '.join(empty_cols)}")
