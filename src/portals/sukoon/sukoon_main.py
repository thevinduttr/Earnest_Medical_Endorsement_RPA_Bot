from __future__ import annotations

from datetime import datetime
import csv
from pathlib import Path
import logging
import shutil
from zipfile import ZIP_DEFLATED, ZipFile

from playwright.async_api import async_playwright

from src.portals.sukoon.add_process.batch_process.batch_add_member import batch_add_member
from src.portals.sukoon.add_process.manual_process.manual_add_member import manual_add_member
from src.portals.sukoon.delete_process.batch_process.batch_delete_member import batch_delete_member
from src.portals.sukoon.delete_process.manual_process.manual_delete_member import manual_delete_member
from src.portals.sukoon.main_process.login import login
from src.services.census_service.sukoon.addition_census import build_addition_census_file
from src.services.census_service.sukoon.deletion_census import (
	build_deletion_census_file,
	load_request_user_ids,
)
from src.services.blob_service.azure_blob_download_service import AzureBlobDownloadService
from src.services.db_service.azure_db_connection import AzureSQLConnection
from src.services.db_service.sukoon_preportal_processor import (
	_download_documents_user_wise,
	_fetch_request_documents_for_users,
)
from src.services.db_service.sukoon_portal_member_error_sync import (
	MemberErrorSyncSummary,
	sync_batch_validation_errors_to_portal_status,
)
from src.services.db_service.sukoon_member_data_loader import load_member_process_values
from src.utils.load_data import load_json_file, load_section_from_yaml, load_yaml_file
from src.utils.upload_file_paths import get_upload_paths


STATUS_TABLE = "[dbo].[EndorsementRequestStatus]"


class InvalidMembersMappedError(RuntimeError):
	"""Validation failed after persisting member-level portal failure reasons."""


def _make_run_id() -> str:
	return datetime.now().strftime("run_%Y-%m-%d_%H-%M-%S")


def _normalize_request_id(value: str | None) -> str | None:
	normalized = str(value or "").strip()
	return normalized or None


def _build_run_log_dir(run_id: str, request_id: str | None) -> Path:
	normalized_request_id = _normalize_request_id(request_id)
	if normalized_request_id:
		return Path("data/logs") / f"request_{normalized_request_id}" / run_id
	return Path("data/logs") / run_id


def _init_logger(run_id: str, request_id: str | None = None) -> logging.Logger:
	run_dir = _build_run_log_dir(run_id=run_id, request_id=request_id)
	run_dir.mkdir(parents=True, exist_ok=True)

	logger = logging.getLogger("sukoon_main")
	logger.setLevel(logging.INFO)

	# Reinitialize handlers per run to avoid duplicate logs in repeated executions.
	if logger.handlers:
		for handler in list(logger.handlers):
			logger.removeHandler(handler)
			try:
				handler.close()
			except Exception:
				pass

	formatter = logging.Formatter(
		"[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
		datefmt="%Y-%m-%d %H:%M:%S",
	)

	file_handler = logging.FileHandler(run_dir / "sukoon_process.log", encoding="utf-8")
	file_handler.setLevel(logging.INFO)
	file_handler.setFormatter(formatter)

	stream_handler = logging.StreamHandler()
	stream_handler.setLevel(logging.INFO)
	stream_handler.setFormatter(formatter)

	logger.addHandler(file_handler)
	logger.addHandler(stream_handler)
	logger.propagate = False
	return logger


def _write_invalid_members_csv(
	*,
	invalid_members: list,
	output_path: Path,
	logger: logging.Logger,
) -> None:
	output_path.parent.mkdir(parents=True, exist_ok=True)
	with output_path.open("w", newline="", encoding="utf-8") as csv_file:
		writer = csv.writer(csv_file)
		writer.writerow(["first_name", "last_name", "eid_number", "employee_number", "error_message"])
		for member in invalid_members:
			writer.writerow(
				[
					getattr(member, "first_name", ""),
					getattr(member, "last_name", ""),
					getattr(member, "eid_number", ""),
					getattr(member, "employee_number", ""),
					getattr(member, "error_message", ""),
				]
			)

	logger.info(f"Invalid members CSV saved: {output_path}")


def _merge_values(base_values: dict, override_values: dict) -> dict:
	merged = dict(base_values or {})
	for key, value in (override_values or {}).items():
		if value is None:
			continue
		if isinstance(value, str) and not value.strip():
			continue
		merged[key] = value
	return merged


def _is_blank_value(value: object) -> bool:
	if value is None:
		return True
	if isinstance(value, str):
		return not value.strip()
	return False


def _validate_manual_add_values(values: dict, logger: logging.Logger) -> None:
	required_fields = {
		"marital_status": "Marital Status",
		"unique_id_visa": "Unique ID (Visa)",
		"category": "Category",
		"residential_location": "Residential Location",
		"work_location": "Work Location",
	}

	missing = [label for key, label in required_fields.items() if _is_blank_value(values.get(key))]
	if missing:
		missing_text = ", ".join(missing)
		logger.error(f"Manual add missing required values: {missing_text}")
		raise ValueError(f"Manual add missing required values: {missing_text}")


def _update_portal_status_for_user(
	*,
	request_id: str | None,
	user_id: str | None,
	status: str,
	failure_reason: str | None,
	logger: logging.Logger,
) -> None:
	request_id = str(request_id or "").strip()
	user_id = str(user_id or "").strip()
	if not request_id or not user_id:
		return

	status_value = str(status or "").strip().upper()
	if not status_value:
		return

	reason_text = str(failure_reason or "").strip()
	if len(reason_text) > 1000:
		reason_text = reason_text[:1000]

	query = f"""
UPDATE {STATUS_TABLE}
SET PortalStatus = ?,
    PortalFailureReason = ?,
    UpdatedAt = SYSUTCDATETIME()
WHERE RequestId = ?
  AND UserId = ?
"""

	with AzureSQLConnection(logger=logger) as db_connection:
		connection = db_connection.connect()
		cursor = connection.cursor()
		try:
			cursor.execute(query, [status_value, reason_text or None, request_id, user_id])
			connection.commit()
		finally:
			cursor.close()

	logger.info(
		"PortalStatus updated for user | "
		f"RequestId={request_id} | UserId={user_id} | Status={status_value}"
	)


def _update_portal_status_for_users(
	*,
	request_id: str | None,
	user_ids: list[str] | None,
	status: str,
	failure_reason: str | None,
	logger: logging.Logger,
) -> None:
	request_id = str(request_id or "").strip()
	normalized_user_ids = [str(user_id).strip() for user_id in (user_ids or []) if str(user_id).strip()]
	if not request_id or not normalized_user_ids:
		return

	status_value = str(status or "").strip().upper()
	if not status_value:
		return

	reason_text = str(failure_reason or "").strip()
	if len(reason_text) > 1000:
		reason_text = reason_text[:1000]

	placeholders = ", ".join("?" for _ in normalized_user_ids)
	query = f"""
UPDATE {STATUS_TABLE}
SET PortalStatus = ?,
    PortalFailureReason = ?,
    UpdatedAt = SYSUTCDATETIME()
WHERE RequestId = ?
  AND UserId IN ({placeholders})
"""

	with AzureSQLConnection(logger=logger) as db_connection:
		connection = db_connection.connect()
		cursor = connection.cursor()
		try:
			cursor.execute(query, [status_value, reason_text or None, request_id, *normalized_user_ids])
			connection.commit()
		finally:
			cursor.close()

	logger.info(
		"PortalStatus updated for users | "
		f"RequestId={request_id} | Users={len(normalized_user_ids)} | Status={status_value}"
	)


def _load_configuration(
	request_type: str,
	action_type: str,
	process_key: str,
	request_id: str | None,
	user_id: str | None,
	use_database: bool,
	logger: logging.Logger,
):
	resolved_request_id = str(request_id or "").strip() or None
	config = load_yaml_file("config/base.yml")
	login_selectors = load_section_from_yaml("locators/sukoon/main/login_page.yml", section="login")
	dashboard_selectors = load_section_from_yaml("locators/sukoon/main/dashboard_page.yml", section="dashboard")
	manual_add_selectors = load_section_from_yaml(
		"locators/sukoon/add_process/manual_add_member.yml",
		section="manual_add_member",
	)
	batch_add_selectors = load_section_from_yaml(
		"locators/sukoon/add_process/batch_add_member.yml",
		section="batch_add_member",
	)
	manual_delete_selectors = load_section_from_yaml(
		"locators/sukoon/delete_process/manual_delete_member.yml",
		section="manual_delete_member",
	)
	batch_delete_selectors = load_section_from_yaml(
		"locators/sukoon/delete_process/batch_delete_member.yml",
		section="batch_delete_member",
	)
	login_values = load_json_file("config/json_values/login.json")
	manual_add_values = load_json_file("config/json_values/manual_add_member.json")
	batch_add_values = load_json_file("config/json_values/batch_add_member.json")
	manual_delete_values = load_json_file("config/json_values/manual_delete_member.json")
	batch_delete_values = load_json_file("config/json_values/batch_delete_member.json")

	if use_database:
		db_result = load_member_process_values(
			portal_name="SUKOON",
			request_type=request_type,
			action_type=action_type,
			process_key=process_key,
			request_id=request_id,
			user_id=user_id if process_key in {"add_individual", "delete_manual"} else None,
			logger=logger,
		)
		logger.info(
			"Database row loaded | "
			f"ResolvedRequestId={db_result.request_id} | "
			f"ProcessKey={process_key}"
		)
		resolved_request_id = db_result.request_id

		if process_key == "add_individual":
			manual_add_values = dict(db_result.process_values)
		elif process_key == "add_batch":
			batch_add_values = _merge_values(batch_add_values, db_result.process_values)
		elif process_key == "delete_manual":
			manual_delete_values = dict(db_result.process_values)
		elif process_key in {"delete_batch", "delete_bulk"}:
			batch_delete_values = _merge_values(batch_delete_values, db_result.process_values)
		else:
			raise RuntimeError(f"Unsupported process key for DB merge: {process_key}")

	return (
		config,
		login_selectors,
		dashboard_selectors,
		manual_add_selectors,
		batch_add_selectors,
		manual_delete_selectors,
		batch_delete_selectors,
		login_values,
		manual_add_values,
		batch_add_values,
		manual_delete_values,
		batch_delete_values,
		resolved_request_id,
	)


def _prepare_batch_census_before_portal(
	process_key: str,
	action_type: str,
	request_type: str,
	resolved_request_id: str | None,
	request_user_ids: list[str] | None,
	upload_paths: dict,
	logger: logging.Logger,
):
	# Step 01: Handle only non-manual processes here.
	if process_key not in {"add_batch", "delete_batch", "delete_bulk"}:
		return

	is_bulk_action = str(action_type or "").strip().upper() == "BULK"
	request_user_ids = [str(user_id).strip() for user_id in (request_user_ids or []) if str(user_id).strip()]

	if not resolved_request_id:
		raise ValueError(
			"RequestId is required to generate batch census file before portal start. "
			"Set RequestId in process_selector.json or enable DB mode with available records."
		)

	destination_root: Path
	if process_key == "add_batch":
		output_path = upload_paths.get("batch_member_file")
	elif process_key in {"delete_batch", "delete_bulk"}:
		output_path = upload_paths.get("batch_delete_member_file")
	else:
		output_path = None

	if not output_path:
		raise ValueError(f"Batch upload output path missing for process: {process_key}")

	# BULK still runs through batch portal forms, so member census files are required.
	if process_key == "add_batch":
		result = build_addition_census_file(
			request_id=resolved_request_id,
			output_path=output_path,
			portal_name="SUKOON",
			include_user_ids=request_user_ids or None,
			logger=logger,
		)
	else:
		result = build_deletion_census_file(
			request_id=resolved_request_id,
			output_path=output_path,
			portal_name="SUKOON",
			include_user_ids=request_user_ids or None,
			logger=logger,
		)
	logger.info(
		"Batch census ready before portal start | "
		f"Template={result.template_path} | Members={result.members_count} | "
		f"Output={result.output_path}"
	)

	if is_bulk_action:
		logger.info("Bulk pre-portal mode selected: census + supporting zip preparation enabled")

	_open_census_in_excel_and_save(result.output_path, logger)
	destination_root = Path(result.output_path).resolve().parent

	_supporting_zip_for_bulk_request(
		request_id=resolved_request_id,
		request_type=request_type,
		request_user_ids=request_user_ids,
		destination_root=destination_root,
		upload_paths=upload_paths,
		logger=logger,
	)


def _prepare_manual_supporting_files(
	*,
	process_key: str,
	request_id: str | None,
	user_id: str | None,
	upload_paths: dict,
	logger: logging.Logger,
) -> None:
	if process_key not in {"add_individual", "delete_manual"}:
		return

	request_id = str(request_id or "").strip()
	user_id = str(user_id or "").strip()
	if not request_id or not user_id:
		logger.warning("Manual supporting docs skipped: RequestId/UserId missing")
		return

	if process_key == "add_individual":
		file_key_1 = "supporting_file_1"
		file_key_2 = "supporting_file_2"
		default_root = Path("data/attachments/samples/sukoon/add/individual")
	else:
		file_key_1 = "delete_supporting_file_1"
		file_key_2 = "delete_supporting_file_2"
		default_root = Path("data/attachments/samples/sukoon/delete/manual")

	primary_path = str(upload_paths.get(file_key_1) or "").strip()
	secondary_path = str(upload_paths.get(file_key_2) or "").strip()
	if primary_path:
		destination_root = Path(primary_path).resolve().parent
	elif secondary_path:
		destination_root = Path(secondary_path).resolve().parent
	else:
		destination_root = default_root

	with AzureSQLConnection(logger=logger) as db_connection:
		connection = db_connection.connect()
		request_documents = _fetch_request_documents_for_users(
			connection=connection,
			request_id=request_id,
			user_ids=[user_id],
		)

	if not request_documents:
		logger.warning(
			"Manual supporting docs not found in DB | "
			f"RequestId={request_id} | UserId={user_id}"
		)
		return

	blob_service = AzureBlobDownloadService(logger=logger)
	_, errors_by_user, all_downloaded = _download_documents_user_wise(
		blob_service=blob_service,
		request_documents=request_documents,
		destination_root=destination_root,
		logger=logger,
	)

	if errors_by_user:
		combined_errors = []
		for member_id, messages in errors_by_user.items():
			combined_errors.extend([f"User {member_id}: {message}" for message in messages])
		logger.warning(
			"Manual supporting docs download errors | "
			f"RequestId={request_id} | UserId={user_id} | "
			f"Errors={" | ".join(combined_errors)[:500]}"
		)

	if not all_downloaded:
		logger.warning(
			"Manual supporting docs download returned no files | "
			f"RequestId={request_id} | UserId={user_id}"
		)
		return

	if len(all_downloaded) <= 2:
		upload_paths[file_key_1] = str(all_downloaded[0])
		upload_paths[file_key_2] = str(all_downloaded[1]) if len(all_downloaded) > 1 else ""
		logger.info(
			"Manual supporting docs mapped to upload paths | "
			f"RequestId={request_id} | UserId={user_id} | Count={len(all_downloaded)}"
		)
		return

	zip_path = destination_root / f"supporting_documents_{request_id}_{user_id}.zip"
	_build_supporting_zip_file(
		zip_path=zip_path,
		downloaded_files=all_downloaded,
		destination_root=destination_root,
		logger=logger,
	)
	upload_paths[file_key_1] = str(zip_path)
	upload_paths[file_key_2] = ""
	logger.info(
		"Manual supporting docs zipped for upload | "
		f"RequestId={request_id} | UserId={user_id} | Files={len(all_downloaded)}"
	)


def _supporting_zip_for_bulk_request(
	request_id: str,
	request_type: str,
	request_user_ids: list[str] | None,
	destination_root: Path,
	upload_paths: dict,
	logger: logging.Logger,
) -> None:
	max_zip_bytes = 4 * 1024 * 1024
	request_type_upper = str(request_type or "").strip().upper()
	if request_type_upper == "ADD":
		primary_key = "batch_supporting_document"
		secondary_key = ""
	else:
		primary_key = "batch_delete_supporting_document_1"
		secondary_key = "batch_delete_supporting_document_2"

	supporting_zip_path = str(upload_paths.get(primary_key) or "").strip()
	if not supporting_zip_path:
		return

	supporting_zip_path_2 = str(upload_paths.get(secondary_key) or "").strip() if secondary_key else ""

	zip_path = Path(supporting_zip_path)
	zip_path.parent.mkdir(parents=True, exist_ok=True)

	zip_path_2 = Path(supporting_zip_path_2) if supporting_zip_path_2 else None
	# Always rebuild zip outputs so stale files (for example old census zips) are never reused.
	zip_path.unlink(missing_ok=True)
	if zip_path_2 and zip_path_2.exists():
		zip_path_2.unlink(missing_ok=True)

	eligible_user_ids = load_request_user_ids(
		request_id=request_id,
		portal_name="SUKOON",
		request_type=request_type_upper,
		logger=logger,
	)

	requested_user_ids = [str(user_id).strip() for user_id in (request_user_ids or []) if str(user_id).strip()]
	if requested_user_ids:
		eligible_set = set(eligible_user_ids)
		user_ids = [user_id for user_id in requested_user_ids if user_id in eligible_set]
	else:
		user_ids = eligible_user_ids

	if not user_ids:
		raise RuntimeError("Bulk supporting docs missing: no users found for request")

	with AzureSQLConnection(logger=logger) as db_connection:
		connection = db_connection.connect()
		request_documents = _fetch_request_documents_for_users(
			connection=connection,
			request_id=request_id,
			user_ids=user_ids,
		)

	if not request_documents:
		raise RuntimeError("Bulk supporting docs missing: no documents available for request")

	blob_service = AzureBlobDownloadService(logger=logger)
	_, errors_by_user, all_downloaded = _download_documents_user_wise(
		blob_service=blob_service,
		request_documents=request_documents,
		destination_root=destination_root,
		logger=logger,
	)

	if not all_downloaded:
		raise RuntimeError("Bulk supporting docs missing: download returned no files")

	compressed_files = _compress_supporting_files(
		files=all_downloaded,
		max_bytes=max_zip_bytes,
		logger=logger,
	)

	# ADD batch/bulk uploads only expose a single supporting-document slot.
	# In that mode, fit everything into one zip (trimmed if required) and avoid
	# artificial secondary bucket generation.
	if supporting_zip_path_2:
		primary_files, secondary_files = _split_files_for_zip(
			files=compressed_files,
			max_bytes=max_zip_bytes,
		)
	else:
		total_bytes = sum(item.stat().st_size for item in compressed_files)
		if total_bytes > max_zip_bytes:
			compressed_files = _trim_supporting_files(
				files=compressed_files,
				max_total_bytes=max_zip_bytes,
				logger=logger,
			)
		primary_files = compressed_files
		secondary_files = []
	_build_supporting_zip_file(
		zip_path=zip_path,
		downloaded_files=primary_files,
		destination_root=destination_root,
		logger=logger,
	)
	if zip_path.stat().st_size > max_zip_bytes:
		raise RuntimeError("Bulk supporting zip exceeds 4MB limit")

	if errors_by_user:
		combined_errors = []
		for user_id, messages in errors_by_user.items():
			combined_errors.extend([f"User {user_id}: {message}" for message in messages])
		reason = " | ".join(combined_errors)[:1000]
		raise RuntimeError(f"Bulk supporting docs download errors: {reason}")

	if secondary_files:
		if not supporting_zip_path_2:
			raise RuntimeError("Supporting docs still require a second upload slot after size optimization")

		zip_path_2 = Path(supporting_zip_path_2)
		_build_supporting_zip_file(
			zip_path=zip_path_2,
			downloaded_files=secondary_files,
			destination_root=destination_root,
			logger=logger,
		)
		if zip_path_2.stat().st_size > max_zip_bytes:
			raise RuntimeError("Bulk supporting zip 2 exceeds 4MB limit")


def _split_files_for_zip(files: list[Path], max_bytes: int) -> tuple[list[Path], list[Path]]:
	primary: list[Path] = []
	secondary: list[Path] = []
	primary_size = 0
	secondary_size = 0

	sorted_files = sorted(files, key=lambda item: item.stat().st_size, reverse=True)
	for file_path in sorted_files:
		file_size = file_path.stat().st_size
		if file_size > max_bytes:
			raise RuntimeError(
				"Bulk delete supporting doc exceeds 4MB limit: "
				f"{file_path.name} ({file_size} bytes)"
			)

		primary_remaining = max_bytes - primary_size
		secondary_remaining = max_bytes - secondary_size
		if file_size <= primary_remaining and file_size <= secondary_remaining:
			if primary_remaining >= secondary_remaining:
				primary.append(file_path)
				primary_size += file_size
			else:
				secondary.append(file_path)
				secondary_size += file_size
			continue

		if file_size <= primary_remaining:
			primary.append(file_path)
			primary_size += file_size
			continue

		if file_size <= secondary_remaining:
			secondary.append(file_path)
			secondary_size += file_size
			continue

		raise RuntimeError("Bulk delete supporting docs exceed 8MB total limit")

	if not primary:
		return [], []

	return primary, secondary


def _compress_supporting_files(
	files: list[Path],
	max_bytes: int,
	logger: logging.Logger,
) -> list[Path]:
	compressed: list[Path] = []
	for file_path in files:
		if file_path.stat().st_size <= max_bytes:
			compressed.append(file_path)
			continue

		compressed_path = _compress_image_file(file_path=file_path, target_bytes=max_bytes, logger=logger)
		compressed.append(compressed_path)

	max_total_bytes = max_bytes * 2
	current_total = sum(item.stat().st_size for item in compressed)
	if current_total <= max_total_bytes:
		return compressed

	compressible = [item for item in compressed if _is_image_file(item)]
	if not compressible:
		return _trim_supporting_files(compressed, max_total_bytes=max_total_bytes, logger=logger)

	compressible_total = sum(item.stat().st_size for item in compressible)
	needed_reduction = current_total - max_total_bytes
	target_total = compressible_total - needed_reduction
	if target_total <= 0:
		return _trim_supporting_files(compressed, max_total_bytes=max_total_bytes, logger=logger)

	ratio = target_total / compressible_total
	adjusted: list[Path] = []
	for file_path in compressed:
		if not _is_image_file(file_path):
			adjusted.append(file_path)
			continue

		current_size = file_path.stat().st_size
		target_bytes = max(200_000, int(current_size * ratio))
		adjusted_path = _compress_image_file(
			file_path=file_path,
			target_bytes=min(target_bytes, max_bytes),
			logger=logger,
		)
		adjusted.append(adjusted_path)

	final_total = sum(item.stat().st_size for item in adjusted)
	if final_total > max_total_bytes:
		return _trim_supporting_files(adjusted, max_total_bytes=max_total_bytes, logger=logger)

	return adjusted


def _compress_image_file(file_path: Path, target_bytes: int, logger: logging.Logger) -> Path:
	if file_path.stat().st_size <= target_bytes:
		return file_path

	file_ext = file_path.suffix.lower()
	if file_ext not in {".jpg", ".jpeg", ".png"}:
		raise RuntimeError(
			"Bulk delete supporting doc exceeds size limit and cannot be compressed: "
			f"{file_path.name} ({file_path.stat().st_size} bytes)"
		)

	try:
		from PIL import Image
	except ImportError as exc:
		raise RuntimeError("Pillow is required to compress large images. Install 'Pillow'.") from exc

	compressed_path = file_path.with_name(f"{file_path.stem}_compressed.jpg")
	with Image.open(file_path) as img:
		if img.mode in {"RGBA", "P"}:
			img = img.convert("RGB")

		quality = 85
		for _ in range(6):
			img.save(compressed_path, format="JPEG", quality=quality, optimize=True)
			if compressed_path.stat().st_size <= target_bytes:
				logger.info(
					"Compressed supporting image | "
					f"Source={file_path.name} | Output={compressed_path.name} | "
					f"Bytes={compressed_path.stat().st_size}"
				)
				return compressed_path
			quality -= 10

		for _ in range(4):
			new_width = max(1, int(img.width * 0.9))
			new_height = max(1, int(img.height * 0.9))
			img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
			img.save(compressed_path, format="JPEG", quality=max(quality, 70), optimize=True)
			if compressed_path.stat().st_size <= target_bytes:
				logger.info(
					"Compressed supporting image after resize | "
					f"Source={file_path.name} | Output={compressed_path.name} | "
					f"Bytes={compressed_path.stat().st_size}"
				)
				return compressed_path

	if compressed_path.stat().st_size > target_bytes:
		raise RuntimeError(
			"Compressed image still exceeds target limit: "
			f"{compressed_path.name} ({compressed_path.stat().st_size} bytes)"
		)

	return compressed_path


def _is_image_file(file_path: Path) -> bool:
	return file_path.suffix.lower() in {".jpg", ".jpeg", ".png"}


def _trim_supporting_files(
	files: list[Path],
	max_total_bytes: int,
	logger: logging.Logger,
) -> list[Path]:
	remaining = list(files)
	total_bytes = sum(item.stat().st_size for item in remaining)
	if total_bytes <= max_total_bytes:
		return remaining

	drop_prefixes = ("OTHERS", "UNKNOWN", "PHOTO", "E_VISA", "PASSPORT")
	for prefix in drop_prefixes:
		candidates = [
			item for item in list(remaining)
			if _document_type_from_filename(item).startswith(prefix)
		]
		for item in candidates:
			remaining.remove(item)
			total_bytes -= item.stat().st_size
			logger.warning(
				"Skipping supporting doc to fit 8MB total limit | "
				f"File={item.name}"
			)
			if total_bytes <= max_total_bytes:
				return remaining

	raise RuntimeError("Bulk delete supporting docs exceed 8MB total limit")


def _document_type_from_filename(file_path: Path) -> str:
	stem = file_path.stem.upper().replace("_COMPRESSED", "")
	if "_" in stem and stem.rsplit("_", 1)[-1].isdigit():
		stem = stem.rsplit("_", 1)[0]
	return stem


def _build_supporting_zip_file(
	zip_path: Path,
	downloaded_files: list[Path],
	destination_root: Path,
	logger: logging.Logger,
) -> None:
	zip_path.parent.mkdir(parents=True, exist_ok=True)
	with ZipFile(zip_path, mode="w", compression=ZIP_DEFLATED) as zip_file:
		for file_path in downloaded_files:
			arcname = Path(file_path).relative_to(destination_root).as_posix()
			zip_file.write(file_path, arcname=arcname)

	logger.info(f"Bulk supporting zip created: {zip_path}")


def _open_census_in_excel_and_save(census_path: str | Path, logger: logging.Logger) -> None:
	resolved_census_path = Path(census_path).resolve()
	if not resolved_census_path.exists():
		raise FileNotFoundError(f"Census file not found for Excel save step: {resolved_census_path}")

	try:
		import pythoncom
		from win32com.client import DispatchEx
	except Exception as exc:
		raise RuntimeError(
			"Excel automation dependency missing. Install pywin32 to enable census open/save/close step."
		) from exc

	excel_app = None
	workbook = None
	pythoncom.CoInitialize()
	try:
		excel_app = DispatchEx("Excel.Application")
		excel_app.Visible = False
		excel_app.DisplayAlerts = False

		workbook = excel_app.Workbooks.Open(
			str(resolved_census_path),
			UpdateLinks=0,
			ReadOnly=False,
		)
		workbook.Save()
		workbook.Close(SaveChanges=True)
		workbook = None

		logger.info(f"Census opened in Excel, saved, and closed: {resolved_census_path}")
	finally:
		if workbook is not None:
			try:
				workbook.Close(SaveChanges=False)
			except Exception:
				pass

		if excel_app is not None:
			try:
				excel_app.Quit()
			except Exception:
				pass

		pythoncom.CoUninitialize()


def _resolve_process_key(request_type: str, action_type: str) -> str:
	request_upper = str(request_type or "").strip().upper()
	action_upper = str(action_type or "").strip().upper()

	if request_upper == "ADD" and action_upper in {"INDIVIDUAL", "MANUAL"}:
		return "add_individual"

	if request_upper == "ADD" and action_upper in {"BATCH", "BULK"}:
		return "add_batch"

	if request_upper == "DELETE" and action_upper in {"INDIVIDUAL", "MANUAL"}:
		return "delete_manual"

	if request_upper == "DELETE" and action_upper == "BATCH":
		return "delete_batch"

	if request_upper == "DELETE" and action_upper == "BULK":
		return "delete_bulk"

	raise NotImplementedError(
		f"Sukoon process not implemented for RequestType={request_upper}, ActionType={action_upper}"
	)


async def run(
	request_type: str,
	action_type: str,
	request_id: str | None = None,
	user_id: str | None = None,
	request_user_ids: list[str] | None = None,
	use_database: bool = True,
):
	run_id = _make_run_id()
	resolved_request_id = _normalize_request_id(request_id)
	resolved_request_user_ids = [str(member_id).strip() for member_id in (request_user_ids or []) if str(member_id).strip()]
	logger = _init_logger(run_id=run_id, request_id=resolved_request_id)
	process_key = _resolve_process_key(request_type=request_type, action_type=action_type)
	logger.info(
		"Input source | "
		f"UseDatabase={use_database} | RequestId={request_id or 'LATEST'} | "
		f"UserId={str(user_id or '').strip() or '-'}"
	)
	if resolved_request_user_ids:
		logger.info(f"Scoped request users received | Count={len(resolved_request_user_ids)}")

	if process_key in {"add_individual", "delete_manual"} and not str(user_id or "").strip():
		raise ValueError("UserId is required for Sukoon manual add/delete processes")

	try:
		(
			config,
			login_selectors,
			dashboard_selectors,
			manual_add_selectors,
			batch_add_selectors,
			manual_delete_selectors,
			batch_delete_selectors,
			login_values,
			manual_add_values,
			batch_add_values,
			manual_delete_values,
			batch_delete_values,
			resolved_request_id,
		) = _load_configuration(
			request_type=request_type,
			action_type=action_type,
			process_key=process_key,
			request_id=request_id,
			user_id=user_id,
			use_database=use_database,
			logger=logger,
		)
	except Exception as exc:
		if use_database and process_key in {"add_individual", "delete_manual"}:
			_update_portal_status_for_user(
				request_id=request_id,
				user_id=user_id,
				status="FAILED",
				failure_reason=str(exc),
				logger=logger,
			)
		elif use_database and request_id and resolved_request_user_ids:
			_update_portal_status_for_users(
				request_id=request_id,
				user_ids=resolved_request_user_ids,
				status="FAILED",
				failure_reason=str(exc),
				logger=logger,
			)
		raise

	resolved_request_id = _normalize_request_id(resolved_request_id)
	logger = _init_logger(run_id=run_id, request_id=resolved_request_id)
	logger.info(
		"Logger initialized for request-specific path | "
		f"RequestId={resolved_request_id or 'UNKNOWN'}"
	)

	# Step 01: Resolve runtime URLs and upload paths.
	base_url = str(config.get("paths", {}).get("base_url") or "https://medical.sukoon.com/")
	upload_paths = get_upload_paths("SUKOON", str(request_type), str(action_type))
	try:
		# Step 02: Validate manual add data before opening the portal.
		if process_key == "add_individual":
			_validate_manual_add_values(manual_add_values, logger)
	except Exception as exc:
		if use_database and process_key in {"add_individual", "delete_manual"}:
			_update_portal_status_for_user(
				request_id=resolved_request_id,
				user_id=user_id,
				status="FAILED",
				failure_reason=str(exc),
				logger=logger,
			)
		raise

	# Step 03: Prepare pre-portal artifacts (census/supporting files) from DB data.
	if use_database:
		try:
			_prepare_batch_census_before_portal(
				process_key=process_key,
				action_type=action_type,
				request_type=request_type,
				resolved_request_id=resolved_request_id,
				request_user_ids=resolved_request_user_ids,
				upload_paths=upload_paths,
				logger=logger,
			)
			_prepare_manual_supporting_files(
				process_key=process_key,
				request_id=resolved_request_id,
				user_id=user_id,
				upload_paths=upload_paths,
				logger=logger,
			)
		except Exception as exc:
			if process_key in {"add_individual", "delete_manual"}:
				_update_portal_status_for_user(
					request_id=resolved_request_id,
					user_id=user_id,
					status="FAILED",
					failure_reason=str(exc),
					logger=logger,
				)
			elif resolved_request_id and resolved_request_user_ids:
				_update_portal_status_for_users(
					request_id=resolved_request_id,
					user_ids=resolved_request_user_ids,
					status="FAILED",
					failure_reason=str(exc),
					logger=logger,
				)
			raise

	# Step 04: Resolve browser launch configuration (always non-persistent context).
	browser_config = config.get("browser", {})
	headless = bool(browser_config.get("headless", False))
	viewport_cfg = browser_config.get("viewport", {})
	width = int(viewport_cfg.get("width", 1920))
	height = int(viewport_cfg.get("height", 945))
	browser_engine = str(browser_config.get("engine") or "msedge").strip().lower()
	runtime_engine = browser_engine
	default_channel = ""
	if browser_engine in {"msedge", "edge"}:
		runtime_engine = "chromium"
		default_channel = "msedge"
	elif browser_engine == "chrome":
		runtime_engine = "chromium"
		default_channel = "chrome"
	browser_channel = str(browser_config.get("channel") or default_channel).strip() or None

	logger.info(f"Starting Sukoon flow | run_id={run_id}")
	logger.info(f"Selected process | RequestType={request_type} | ActionType={action_type} | ProcessKey={process_key}")
	logger.info(f"Opening URL: {base_url}")
	logger.info(
		"Browser launch mode | "
		f"Engine={browser_engine} | "
		f"Channel={browser_channel or '-'}"
	)

	page = None
	browser = None
	run_dir = _build_run_log_dir(run_id=run_id, request_id=resolved_request_id)

	# Step 05: Launch browser and execute the selected Sukoon process.
	async with async_playwright() as playwright:
		context = None

		if runtime_engine == "chromium":
			browser = await playwright.chromium.launch(
				headless=headless,
				channel=browser_channel,
			)
		elif runtime_engine == "firefox":
			browser = await playwright.firefox.launch(headless=headless)
		elif runtime_engine == "webkit":
			browser = await playwright.webkit.launch(headless=headless)
		else:
			raise ValueError(f"Unsupported browser engine: {browser_engine}")

		context = await browser.new_context(viewport={"width": width, "height": height})
		page = await context.new_page()

		try:
			await page.goto(base_url, wait_until="domcontentloaded")

			await login(
				page=page,
				login_values=login_values,
				login_selectors=login_selectors,
				dashboard_selectors=dashboard_selectors,
				logger=logger,
			)

			login_success_shot = run_dir / "login_success.png"
			await page.screenshot(path=str(login_success_shot), full_page=True)
			logger.info(f"Saved login success screenshot: {login_success_shot}")

			if process_key == "add_individual":
				await manual_add_member(
					page=page,
					manual_selectors=manual_add_selectors,
					manual_values=manual_add_values,
					upload_paths=upload_paths,
					logger=logger,
				)

				success_shot = run_dir / "manual_add_success.png"
				await page.screenshot(path=str(success_shot), full_page=True)
				logger.info(f"Saved manual add success screenshot: {success_shot}")

				if use_database:
					_update_portal_status_for_user(
						request_id=resolved_request_id,
						user_id=user_id,
						status="SUCCESS",
						failure_reason=None,
						logger=logger,
					)

			elif process_key == "add_batch":
				batch_result = await batch_add_member(
					page=page,
					batch_selectors=batch_add_selectors,
					batch_values=batch_add_values,
					upload_paths=upload_paths,
					logger=logger,
				)

				if batch_result.invalid_members:
					invalid_members_csv = run_dir / "batch_add_invalid_members.csv"
					_write_invalid_members_csv(
						invalid_members=batch_result.invalid_members,
						output_path=invalid_members_csv,
						logger=logger,
					)

					sync_summary = MemberErrorSyncSummary(mapped_rows=0, updated_users=0, unmapped_rows=0)
					if use_database and resolved_request_id:
						sync_summary = sync_batch_validation_errors_to_portal_status(
							request_id=resolved_request_id,
							invalid_members=batch_result.invalid_members,
							portal_name="SUKOON",
							request_type=request_type,
							logger=logger,
						)

					logger.error(
						"Batch validation failed with member errors | "
						f"Members={len(batch_result.invalid_members)} | "
						f"MappedRows={sync_summary.mapped_rows} | "
						f"UpdatedUsers={sync_summary.updated_users} | "
						f"UnmappedRows={sync_summary.unmapped_rows}"
					)
					raise InvalidMembersMappedError(
						"Batch validate returned Invalid Members. "
						"PortalStatus was updated to FAILED for mapped members."
					)

				success_shot = run_dir / "batch_add_success.png"
				await page.screenshot(path=str(success_shot), full_page=True)
				logger.info(f"Saved batch add success screenshot: {success_shot}")

				if use_database and resolved_request_id and resolved_request_user_ids:
					_update_portal_status_for_users(
						request_id=resolved_request_id,
						user_ids=resolved_request_user_ids,
						status="SUCCESS",
						failure_reason=None,
						logger=logger,
					)

			elif process_key == "delete_manual":
				await manual_delete_member(
					page=page,
					delete_selectors=manual_delete_selectors,
					delete_values=manual_delete_values,
					upload_paths=upload_paths,
					logger=logger,
				)

				success_shot = run_dir / "manual_delete_success.png"
				await page.screenshot(path=str(success_shot), full_page=True)
				logger.info(f"Saved manual delete success screenshot: {success_shot}")

				if use_database:
					_update_portal_status_for_user(
						request_id=resolved_request_id,
						user_id=user_id,
						status="SUCCESS",
						failure_reason=None,
						logger=logger,
					)

			elif process_key in {"delete_batch", "delete_bulk"}:
				await batch_delete_member(
					page=page,
					delete_selectors=batch_delete_selectors,
					delete_values=batch_delete_values,
					upload_paths=upload_paths,
					logger=logger,
				)

				success_shot = run_dir / "batch_delete_success.png"
				await page.screenshot(path=str(success_shot), full_page=True)
				logger.info(f"Saved batch delete success screenshot: {success_shot}")

				if use_database and resolved_request_id and resolved_request_user_ids:
					_update_portal_status_for_users(
						request_id=resolved_request_id,
						user_ids=resolved_request_user_ids,
						status="SUCCESS",
						failure_reason=None,
						logger=logger,
					)

			else:
				raise RuntimeError(f"Unhandled Sukoon process key: {process_key}")

		except Exception as exc:
			logger.error(f"Sukoon run failed: {exc}")
			skip_generic_failure_update = isinstance(exc, InvalidMembersMappedError)
			if use_database and process_key in {"add_individual", "delete_manual"} and not skip_generic_failure_update:
				_update_portal_status_for_user(
					request_id=resolved_request_id,
					user_id=user_id,
					status="FAILED",
					failure_reason=str(exc),
					logger=logger,
				)
			elif use_database and resolved_request_id and resolved_request_user_ids and not skip_generic_failure_update:
				_update_portal_status_for_users(
					request_id=resolved_request_id,
					user_ids=resolved_request_user_ids,
					status="FAILED",
					failure_reason=str(exc),
					logger=logger,
				)
			if page is not None:
				try:
					error_shot = run_dir / "login_error.png"
					await page.screenshot(path=str(error_shot), full_page=True)
					logger.info(f"Saved error screenshot: {error_shot}")
				except Exception as shot_exc:
					logger.error(f"Failed to save error screenshot: {shot_exc}")
			raise
		finally:
			if context is not None:
				await context.close()
			if browser is not None:
				await browser.close()

