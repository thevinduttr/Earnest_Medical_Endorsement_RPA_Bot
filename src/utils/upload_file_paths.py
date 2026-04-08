from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple


ProcessKey = Tuple[str, str, str]


def _build_file_map(base_dir: Path) -> Dict[ProcessKey, Dict[str, str]]:
    return {
        ("SUKOON", "ADD", "INDIVIDUAL"): {
            "supporting_file_1": str(
                (base_dir / "sukoon" / "add" / "individual" / "supporting_file_1.pdf").resolve()
            ),
            "supporting_file_2": str(
                (base_dir / "sukoon" / "add" / "individual" / "supporting_file_2.pdf").resolve()
            ),
        },
        ("SUKOON", "ADD", "BATCH"): {
            "batch_member_file": str(
                (base_dir / "sukoon" / "add" / "batch" / "member_addition.xlsx").resolve()
            ),
            "batch_supporting_document": str(
                (base_dir / "sukoon" / "add" / "batch" / "supporting_document.zip").resolve()
            ),
        },
        ("SUKOON", "DELETE", "INDIVIDUAL"): {
            "delete_supporting_file_1": str(
                (base_dir / "sukoon" / "delete" / "manual" / "supporting_file_1.pdf").resolve()
            ),
            "delete_supporting_file_2": str(
                (base_dir / "sukoon" / "delete" / "manual" / "supporting_file_2.pdf").resolve()
            ),
        },
        ("SUKOON", "DELETE", "BATCH"): {
            "batch_delete_member_file": str(
                (base_dir / "sukoon" / "delete" / "batch" / "member_deletion.xlsx").resolve()
            ),
            "batch_delete_supporting_document_1": str(
                (base_dir / "sukoon" / "delete" / "batch" / "supporting_document_1.zip").resolve()
            ),
            "batch_delete_supporting_document_2": str(
                (base_dir / "sukoon" / "delete" / "batch" / "supporting_document_2.zip").resolve()
            ),
        },
    }


def get_upload_paths(portal_name: str, request_type: str, action_type: str) -> Dict[str, str]:
    key = (str(portal_name).upper(), str(request_type).upper(), str(action_type).upper())
    base_dir = Path("data/attachments/samples")
    file_map = _build_file_map(base_dir)
    return dict(file_map.get(key, {}))
