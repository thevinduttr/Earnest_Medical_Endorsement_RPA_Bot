import asyncio
import shutil
from pathlib import Path

from src.portals.sukoon.sukoon_main import run as run_sukoon
from src.services.db_service.sukoon_member_data_loader import load_process_selector_by_request_id
from src.services.db_service.sukoon_preportal_processor import prepare_sukoon_requests_without_portal
from src.utils.load_data import load_json_file
from src.utils.process_context import (
	parse_process_selector,
	parse_request_id,
	parse_run_portal,
	parse_use_database,
)


def _clear_attachments_workspace() -> None:
	attachments_root = Path("data/attachments")
	attachments_root.mkdir(parents=True, exist_ok=True)

	removed_files = 0
	removed_dirs = 0

	for item in attachments_root.iterdir():
		if item.is_file() or item.is_symlink():
			item.unlink(missing_ok=True)
			removed_files += 1
		elif item.is_dir():
			shutil.rmtree(item, ignore_errors=False)
			removed_dirs += 1

	print(
		"Attachments workspace cleared | "
		f"FilesRemoved={removed_files} DirsRemoved={removed_dirs}"
	)


async def _run_selected_process():
	_clear_attachments_workspace()

	selector_data = load_json_file("config/json_values/process_selector.json")
	request_id = parse_request_id(selector_data)
	use_database = parse_use_database(selector_data, default=True)
	run_portal = parse_run_portal(selector_data, default=True)

	if use_database and request_id:
		db_selector = load_process_selector_by_request_id(request_id=request_id)
		selector_data = {
			**selector_data,
			"PortalName": db_selector["PortalName"],
			"RequestType": db_selector["RequestType"],
			"ActionType": db_selector["ActionType"],
		}

	portal_name, request_type, action_type = parse_process_selector(selector_data)

	if not run_portal:
		if portal_name == "SUKOON":
			summary = prepare_sukoon_requests_without_portal(target_request_id=request_id)
			print(
				"SUKOON pre-portal preparation completed | "
				f"Total={summary.total_requests} "
				f"Completed={summary.completed_requests} "
				f"Failed={summary.failed_requests} "
				f"Skipped={summary.skipped_requests}"
			)
			return

		if portal_name == "NAS":
			raise NotImplementedError("NAS pre-portal processor is not developed yet")

		raise NotImplementedError(f"Unsupported PortalName for pre-portal mode: {portal_name}")

	if portal_name == "SUKOON":
		await run_sukoon(
			request_type=request_type,
			action_type=action_type,
			request_id=request_id,
			use_database=use_database,
		)
		return

	if portal_name == "NAS":
		raise NotImplementedError("NAS processes are not developed yet")

	raise NotImplementedError(f"Unsupported PortalName: {portal_name}")


if __name__ == "__main__":
	asyncio.run(_run_selected_process())