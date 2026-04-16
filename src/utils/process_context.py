from __future__ import annotations

from typing import Any, Dict, Tuple


_ALLOWED_REQUEST_TYPES = {"ADD", "DELETE"}
_ALLOWED_ACTION_TYPES = {"INDIVIDUAL", "BATCH"}
_ALLOWED_PORTALS = {"SUKOON", "NAS"}
_ACTION_ALIASES = {
    "MANUAL": "INDIVIDUAL",
    "MANNUAL": "INDIVIDUAL",
    "INDIVIDUAL": "INDIVIDUAL",
    "INDIVIDUAL(MANUAL)": "INDIVIDUAL",
    "INDIVIDUAL_MANUAL": "INDIVIDUAL",
    "BATCH": "BATCH",
    "BULK": "BATCH",
}


def _normalize(value: Any) -> str:
    return str(value or "").strip().upper()


def parse_process_selector(selector_data: Dict[str, Any]) -> Tuple[str, str, str]:
    portal_name = _normalize(selector_data.get("PortalName"))
    request_type = _normalize(selector_data.get("RequestType"))
    action_type_raw = _normalize(selector_data.get("ActionType"))

    action_type = _ACTION_ALIASES.get(action_type_raw, action_type_raw)

    if portal_name not in _ALLOWED_PORTALS:
        raise ValueError(
            f"Invalid PortalName '{portal_name}'. Supported: {', '.join(sorted(_ALLOWED_PORTALS))}"
        )

    if request_type not in _ALLOWED_REQUEST_TYPES:
        raise ValueError(
            f"Invalid RequestType '{request_type}'. Supported: {', '.join(sorted(_ALLOWED_REQUEST_TYPES))}"
        )

    if action_type not in _ALLOWED_ACTION_TYPES:
        raise ValueError(
            f"Invalid ActionType '{action_type_raw}'. Supported: INDIVIDUAL (or MANUAL), BATCH"
        )

    return portal_name, request_type, action_type


def parse_use_database(selector_data: Dict[str, Any], default: bool = True) -> bool:
    raw_value = selector_data.get("UseDatabase", default)
    if isinstance(raw_value, bool):
        return raw_value

    normalized = _normalize(raw_value)
    if normalized in {"TRUE", "1", "YES", "Y"}:
        return True
    if normalized in {"FALSE", "0", "NO", "N"}:
        return False

    raise ValueError(
        f"Invalid UseDatabase value '{raw_value}'. Supported: true/false, yes/no, 1/0"
    )


def parse_run_portal(selector_data: Dict[str, Any], default: bool = True) -> bool:
    raw_value = selector_data.get("RunPortal", default)
    if isinstance(raw_value, bool):
        return raw_value

    normalized = _normalize(raw_value)
    if normalized in {"TRUE", "1", "YES", "Y"}:
        return True
    if normalized in {"FALSE", "0", "NO", "N"}:
        return False

    raise ValueError(
        f"Invalid RunPortal value '{raw_value}'. Supported: true/false, yes/no, 1/0"
    )


def parse_request_id(selector_data: Dict[str, Any]) -> str | None:
    raw_value = selector_data.get("RequestId")
    if raw_value is None:
        return None

    request_id = str(raw_value).strip()
    return request_id or None


def parse_user_id(selector_data: Dict[str, Any]) -> str | None:
    raw_value = selector_data.get("UserId")
    if raw_value is None:
        return None

    user_id = str(raw_value).strip()
    return user_id or None
