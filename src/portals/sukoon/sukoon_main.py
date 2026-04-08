from __future__ import annotations

from datetime import datetime
from pathlib import Path
import logging
from zipfile import ZIP_DEFLATED, ZipFile

from playwright.async_api import async_playwright

from src.portals.sukoon.add_process.batch_process.batch_add_member import batch_add_member
from src.portals.sukoon.add_process.manual_process.manual_add_member import manual_add_member
from src.portals.sukoon.delete_process.batch_process.batch_delete_member import batch_delete_member
from src.portals.sukoon.delete_process.manual_process.manual_delete_member import manual_delete_member
from src.portals.sukoon.main_process.login import login
from src.services.db_service.sukoon_batch_census_builder import build_batch_census_file
from src.services.db_service.sukoon_portal_member_error_sync import (
	MemberErrorSyncSummary,
	sync_batch_validation_errors_to_portal_status,
)
from src.services.db_service.sukoon_member_data_loader import load_member_process_values
from src.utils.load_data import load_json_file, load_section_from_yaml, load_yaml_file
from src.utils.upload_file_paths import get_upload_paths


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


def _merge_values(base_values: dict, override_values: dict) -> dict:
	merged = dict(base_values or {})
	for key, value in (override_values or {}).items():
		if value is None:
			continue
		if isinstance(value, str) and not value.strip():
			continue
		merged[key] = value
	return merged


def _load_configuration(
	request_type: str,
	action_type: str,
	process_key: str,
	request_id: str | None,
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
			logger=logger,
		)
		logger.info(
			"Database row loaded | "
			f"ResolvedRequestId={db_result.request_id} | "
			f"ProcessKey={process_key}"
		)
		resolved_request_id = db_result.request_id

		if process_key == "add_individual":
			manual_add_values = _merge_values(manual_add_values, db_result.process_values)
		elif process_key == "add_batch":
			batch_add_values = _merge_values(batch_add_values, db_result.process_values)
		elif process_key == "delete_manual":
			manual_delete_values = _merge_values(manual_delete_values, db_result.process_values)
		elif process_key == "delete_batch":
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
	request_type: str,
	resolved_request_id: str | None,
	upload_paths: dict,
	logger: logging.Logger,
):
	if process_key not in {"add_batch", "delete_batch"}:
		return

	if not resolved_request_id:
		raise ValueError(
			"RequestId is required to generate batch census file before portal start. "
			"Set RequestId in process_selector.json or enable DB mode with available records."
		)

	if process_key == "add_batch":
		output_path = upload_paths.get("batch_member_file")
	elif process_key == "delete_batch":
		output_path = upload_paths.get("batch_delete_member_file")
	else:
		output_path = None

	if not output_path:
		raise ValueError(f"Batch upload output path missing for process: {process_key}")

	result = build_batch_census_file(
		request_id=resolved_request_id,
		request_type=request_type,
		output_path=output_path,
		portal_name="SUKOON",
		logger=logger,
	)
	logger.info(
		"Batch census ready before portal start | "
		f"Template={result.template_path} | Members={result.members_count} | "
		f"Output={result.output_path}"
	)

	_open_census_in_excel_and_save(result.output_path, logger)

	if process_key == "add_batch":
		supporting_zip_path = str(upload_paths.get("batch_supporting_document") or "").strip()
		if supporting_zip_path:
			zip_path = Path(supporting_zip_path)
			zip_path.parent.mkdir(parents=True, exist_ok=True)

			if not zip_path.exists() or zip_path.stat().st_size == 0:
				source_file = Path(str(result.output_path))
				if source_file.exists():
					with ZipFile(zip_path, mode="w", compression=ZIP_DEFLATED) as archive:
						archive.write(source_file, arcname=source_file.name)
					logger.info(
						"Generated batch supporting document ZIP | "
						f"Source={source_file} | Output={zip_path}"
					)
				else:
					logger.warning(
						"Batch supporting ZIP generation skipped because census output was not found | "
						f"ExpectedSource={source_file}"
					)


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

	if request_upper == "ADD" and action_upper == "BATCH":
		return "add_batch"

	if request_upper == "DELETE" and action_upper in {"INDIVIDUAL", "MANUAL"}:
		return "delete_manual"

	if request_upper == "DELETE" and action_upper == "BATCH":
		return "delete_batch"

	raise NotImplementedError(
		f"Sukoon process not implemented for RequestType={request_upper}, ActionType={action_upper}"
	)


async def run(
	request_type: str,
	action_type: str,
	request_id: str | None = None,
	use_database: bool = True,
):
	run_id = _make_run_id()
	resolved_request_id = _normalize_request_id(request_id)
	logger = _init_logger(run_id=run_id, request_id=resolved_request_id)
	process_key = _resolve_process_key(request_type=request_type, action_type=action_type)
	logger.info(f"Input source | UseDatabase={use_database} | RequestId={request_id or 'LATEST'}")

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
		use_database=use_database,
		logger=logger,
	)

	resolved_request_id = _normalize_request_id(resolved_request_id)
	logger = _init_logger(run_id=run_id, request_id=resolved_request_id)
	logger.info(
		"Logger initialized for request-specific path | "
		f"RequestId={resolved_request_id or 'UNKNOWN'}"
	)

	base_url = str(config.get("paths", {}).get("base_url") or "https://medical.sukoon.com/")
	upload_paths = get_upload_paths("SUKOON", str(request_type), str(action_type))

	if use_database:
		_prepare_batch_census_before_portal(
			process_key=process_key,
			request_type=request_type,
			resolved_request_id=resolved_request_id,
			upload_paths=upload_paths,
			logger=logger,
		)

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
	persistent_context = bool(browser_config.get("persistent_context", True))
	user_data_dir_value = str(browser_config.get("user_data_dir") or "data/browser_profiles/sukoon").strip()
	user_data_dir = str(Path(user_data_dir_value).resolve())

	logger.info(f"Starting Sukoon flow | run_id={run_id}")
	logger.info(f"Selected process | RequestType={request_type} | ActionType={action_type} | ProcessKey={process_key}")
	logger.info(f"Opening URL: {base_url}")
	logger.info(
		"Browser launch mode | "
		f"Engine={browser_engine} | "
		f"Channel={browser_channel or '-'} | "
		f"PersistentContext={persistent_context} | "
		f"Profile={user_data_dir if persistent_context else '-'}"
	)

	page = None
	browser = None
	run_dir = _build_run_log_dir(run_id=run_id, request_id=resolved_request_id)

	async with async_playwright() as playwright:
		context = None

		if persistent_context:
			if runtime_engine == "chromium":
				context = await playwright.chromium.launch_persistent_context(
					user_data_dir=user_data_dir,
					headless=headless,
					channel=browser_channel,
					viewport={"width": width, "height": height},
				)
			elif runtime_engine == "firefox":
				context = await playwright.firefox.launch_persistent_context(
					user_data_dir=user_data_dir,
					headless=headless,
					viewport={"width": width, "height": height},
				)
			elif runtime_engine == "webkit":
				context = await playwright.webkit.launch_persistent_context(
					user_data_dir=user_data_dir,
					headless=headless,
					viewport={"width": width, "height": height},
				)
			else:
				raise ValueError(f"Unsupported browser engine: {browser_engine}")

			page = context.pages[0] if context.pages else await context.new_page()
		else:
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

			elif process_key == "add_batch":
				batch_result = await batch_add_member(
					page=page,
					batch_selectors=batch_add_selectors,
					batch_values=batch_add_values,
					upload_paths=upload_paths,
					logger=logger,
				)

				if batch_result.invalid_members:
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
					raise RuntimeError(
						"Batch validate returned Invalid Members. "
						"PortalStatus was updated to FAILED for mapped members."
					)

				success_shot = run_dir / "batch_add_success.png"
				await page.screenshot(path=str(success_shot), full_page=True)
				logger.info(f"Saved batch add success screenshot: {success_shot}")

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

			elif process_key == "delete_batch":
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

			else:
				raise RuntimeError(f"Unhandled Sukoon process key: {process_key}")

		except Exception as exc:
			logger.error(f"Sukoon run failed: {exc}")
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

