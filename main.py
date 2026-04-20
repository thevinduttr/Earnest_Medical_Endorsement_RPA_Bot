from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from src.portals.sukoon.sukoon_main import InvalidMembersMappedError, run as run_sukoon
from src.services.db_service.sukoon_member_data_loader import load_process_selector_by_request_id
from src.services.db_service.sukoon_preportal_processor import (
	ClaimedRequest,
	claim_next_pending_request,
	update_portal_status_for_users,
)
from src.utils.load_data import load_yaml_file
from src.utils.process_context import parse_process_selector


@dataclass(frozen=True)
class WorkerSettings:
	poll_interval_seconds: float
	failure_sleep_seconds: float
	loop_sleep_seconds: float
	clear_attachments_each_cycle: bool
	max_iterations: int


def _build_logger() -> logging.Logger:
	logger = logging.getLogger("endorsement_worker")
	logger.setLevel(logging.INFO)
	if logger.handlers:
		return logger

	handler = logging.StreamHandler()
	handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
	logger.addHandler(handler)
	logger.propagate = False
	return logger


def _safe_float(value: object, default: float) -> float:
	try:
		resolved = float(value)
	except (TypeError, ValueError):
		return default
	return resolved if resolved >= 0 else default


def _safe_int(value: object, default: int) -> int:
	try:
		resolved = int(str(value).strip())
	except (TypeError, ValueError):
		return default
	return resolved if resolved >= 0 else default


def _load_worker_settings() -> WorkerSettings:
	config = load_yaml_file("config/base.yml")
	worker_cfg = config.get("worker", {}) if isinstance(config, dict) else {}

	poll_interval_seconds = _safe_float(
		os.getenv("WORKER_POLL_INTERVAL_SECONDS", worker_cfg.get("poll_interval_seconds")),
		10.0,
	)
	failure_sleep_seconds = _safe_float(
		os.getenv("WORKER_FAILURE_SLEEP_SECONDS", worker_cfg.get("failure_sleep_seconds")),
		2.0,
	)
	loop_sleep_seconds = _safe_float(
		os.getenv("WORKER_LOOP_SLEEP_SECONDS", worker_cfg.get("loop_sleep_seconds")),
		0.2,
	)
	clear_attachments_each_cycle = bool(worker_cfg.get("clear_attachments_each_cycle", True))
	max_iterations = _safe_int(os.getenv("WORKER_MAX_ITERATIONS"), 0)

	return WorkerSettings(
		poll_interval_seconds=poll_interval_seconds,
		failure_sleep_seconds=failure_sleep_seconds,
		loop_sleep_seconds=loop_sleep_seconds,
		clear_attachments_each_cycle=clear_attachments_each_cycle,
		max_iterations=max_iterations,
	)


def _clear_attachments_workspace(logger: logging.Logger) -> None:
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

	logger.info(
		"Attachments workspace cleared | "
		f"FilesRemoved={removed_files} | DirsRemoved={removed_dirs}"
	)


async def _process_sukoon_claim(
	*,
	request_id: str,
	request_type: str,
	action_type: str,
	user_ids: list[str],
	logger: logging.Logger,
) -> None:
	if action_type == "INDIVIDUAL":
		for user_id in user_ids:
			try:
				await run_sukoon(
					request_type=request_type,
					action_type=action_type,
					request_id=request_id,
					user_id=user_id,
					request_user_ids=[user_id],
					use_database=True,
				)
			except Exception as exc:
				logger.exception(
					"SUKOON individual processing failed | RequestId=%s | UserId=%s | Error=%s",
					request_id,
					user_id,
					exc,
				)
				update_portal_status_for_users(
					request_id=request_id,
					user_ids=[user_id],
					status="FAILED",
					failure_reason=str(exc),
					logger=logger,
				)
		return

	await run_sukoon(
		request_type=request_type,
		action_type=action_type,
		request_id=request_id,
		user_id=None,
		request_user_ids=user_ids,
		use_database=True,
	)


def _process_nas_claim(*, request_id: str, user_ids: list[str], logger: logging.Logger) -> None:
	reason = "NAS portal processing is not implemented in this repository"
	update_portal_status_for_users(
		request_id=request_id,
		user_ids=user_ids,
		status="FAILED",
		failure_reason=reason,
		logger=logger,
	)
	logger.error("NAS request marked as FAILED | RequestId=%s | Users=%s", request_id, len(user_ids))


async def _dispatch_claimed_request(claimed: ClaimedRequest, logger: logging.Logger) -> None:
	request_id = str(claimed.request_id or "").strip()
	user_ids = [str(user_id).strip() for user_id in claimed.user_ids if str(user_id).strip()]
	if not request_id or not user_ids:
		return

	selector = load_process_selector_by_request_id(request_id=request_id, logger=logger)
	portal_name, request_type, action_type = parse_process_selector(selector)

	logger.info(
		"Dispatching request | RequestId=%s | Portal=%s | RequestType=%s | ActionType=%s | Users=%s",
		request_id,
		portal_name,
		request_type,
		action_type,
		len(user_ids),
	)

	if portal_name == "SUKOON":
		await _process_sukoon_claim(
			request_id=request_id,
			request_type=request_type,
			action_type=action_type,
			user_ids=user_ids,
			logger=logger,
		)
		return

	if portal_name == "NAS":
		_process_nas_claim(request_id=request_id, user_ids=user_ids, logger=logger)
		return

	raise ValueError(f"Unsupported PortalName: {portal_name}")


async def _run_queue_worker() -> None:
	settings = _load_worker_settings()
	logger = _build_logger()
	logger.info(
		"Worker started | PollInterval=%ss | FailureSleep=%ss | LoopSleep=%ss | MaxIterations=%s",
		settings.poll_interval_seconds,
		settings.failure_sleep_seconds,
		settings.loop_sleep_seconds,
		settings.max_iterations or "infinite",
	)

	iteration = 0
	while True:
		if settings.max_iterations and iteration >= settings.max_iterations:
			logger.info("Worker stopped after max iterations: %s", settings.max_iterations)
			return

		iteration += 1
		claimed = claim_next_pending_request(logger=logger)
		if claimed is None:
			await asyncio.sleep(settings.poll_interval_seconds)
			continue

		try:
			if settings.clear_attachments_each_cycle:
				_clear_attachments_workspace(logger)
			await _dispatch_claimed_request(claimed=claimed, logger=logger)
		except Exception as exc:
			logger.exception(
				"Claimed request failed | RequestId=%s | Users=%s | Error=%s",
				claimed.request_id,
				len(claimed.user_ids),
				exc,
			)
			if not isinstance(exc, InvalidMembersMappedError):
				update_portal_status_for_users(
					request_id=claimed.request_id,
					user_ids=claimed.user_ids,
					status="FAILED",
					failure_reason=str(exc),
					logger=logger,
				)
			await asyncio.sleep(settings.failure_sleep_seconds)
			continue

		await asyncio.sleep(settings.loop_sleep_seconds)


if __name__ == "__main__":
	try:
		asyncio.run(_run_queue_worker())
	except KeyboardInterrupt:
		pass