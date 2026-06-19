from __future__ import annotations

from datetime import datetime
from pathlib import Path
import logging
import os

from playwright.async_api import async_playwright

from src.portals.nas.add_process.bulk_member.bulk_add_member import (
    NasBulkValidationDownloadError,
    resolve_payer_name_from_email_filename,
    run_bulk_add_member,
)
from src.portals.nas.add_process.member.master_contract_page import select_company_accordion
from src.portals.nas.add_process.member.sub_policy_page import select_sub_policy_add_member
from src.portals.nas.main_process.login import login
from src.services.mail_service.outlook_mail_service import send_outlook_email
from src.services.mail_service.sukoon_email_templates import (
    build_unexpected_body,
    build_unexpected_subject,
    build_validation_body,
    build_validation_subject,
)
from src.portals.nas.main_process.new_button_page import open_new_member_page
from src.portals.nas.main_process.request_dashboard_page import open_request_dashboard_page
from src.services.db_service.nas.member_data_loader import (
    load_latest_request_email_filename,
    load_member_process_values,
    load_process_selector,
)
from src.services.census_service.nas.addition_census import (
    build_nas_addition_census_file,
)
from src.services.census_service.nas.deletion_census import (
    build_nas_deletion_census_file,
)
from src.utils.load_data import load_json_file, load_section_from_yaml, load_yaml_file
from src.utils.mail_config import MailConfig
from src.utils.upload_file_paths import get_upload_paths


DEFAULT_NAS_LOGIN_URL = (
    "https://nsecure.nnhs.ae/Accounts/login?"
    "returnUrl=%2Fconnect%2Fauthorize%3Fclient_id%3Drhr6or1ivz4nx1g42h7v"
    "%26redirect_uri%3Dhttps%253A%252F%252Fntouch.nnhs.ae%252FBrokerConnect%252F"
    "%26response_type%3Dcode%26scope%3Dopenid"
)


def _make_run_id() -> str:
    return datetime.now().strftime("run_%Y-%m-%d_%H-%M-%S")


def _build_run_log_dir(run_id: str, request_id: str | None) -> Path:
    request_id_text = str(request_id or "").strip()
    if request_id_text:
        return Path("data/logs") / f"request_{request_id_text}" / run_id
    return Path("data/logs") / run_id


def _init_logger(run_id: str, request_id: str | None = None) -> logging.Logger:
    run_dir = _build_run_log_dir(run_id=run_id, request_id=request_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("nas_main")
    logger.setLevel(logging.INFO)

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

    file_handler = logging.FileHandler(run_dir / "nas_process.log", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.propagate = False
    return logger


def _resolve_process_key(request_type: str, action_type: str) -> str:
    request_upper = str(request_type or "").strip().upper()
    action_upper = str(action_type or "").strip().upper()

    if request_upper == "ADD" and action_upper in {"INDIVIDUAL", "MANUAL"}:
        return "add_individual"

    if request_upper == "ADD" and action_upper in {"BATCH", "BULK"}:
        return "add_batch"

    if request_upper == "ADD" and action_upper in {"FAMILY", "FAMILY_MEMBER"}:
        return "add_family"

    if request_upper == "DELETE" and action_upper in {"INDIVIDUAL", "MANUAL"}:
        return "delete_manual"

    if request_upper == "DELETE" and action_upper == "BATCH":
        return "delete_batch"

    if request_upper == "DELETE" and action_upper == "BULK":
        return "delete_bulk"

    raise NotImplementedError(
        f"NAS process not implemented for RequestType={request_upper}, ActionType={action_upper}"
    )


def _merge_values(base_values: dict, override_values: dict) -> dict:
    merged = dict(base_values or {})
    for key, value in (override_values or {}).items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        merged[key] = value
    return merged


def _resolve_policy_number(process_values: dict) -> str:
    for key in ("PolicyNumber", "policy_number", "company_name", "CompanyName"):
        value = str(process_values.get(key, "")).strip()
        if value:
            return value
    return ""


def _build_mail_process_data(
    *,
    request_id: str | None,
    policy_number: str,
    action_type: str,
    portal_name: str = "NAS",
    status: str,
    reference_number: str = "",
) -> dict[str, str]:
    return {
        "RequestId": str(request_id or "").strip(),
        "PolicyNumber": str(policy_number or "").strip(),
        "ActionType": str(action_type or "").strip(),
        "PortalName": str(portal_name or "").strip(),
        "Status": str(status or "").strip(),
        "ReferenceNumber": str(reference_number or "").strip(),
    }


def _read_bool_env(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _send_nas_error_email(
    *,
    process_data: dict[str, str],
    error_message: str,
    screenshot_paths: list[Path],
    logger: logging.Logger,
    retry_count: int = 3,
) -> None:
    try:
        mail_config = MailConfig.load(Path("config/mail.ini"))
        attachments = [path for path in screenshot_paths if path.exists()]
        subject = build_unexpected_subject(
            str(process_data.get("RequestId", "")).strip(),
            str(process_data.get("PolicyNumber", "")).strip(),
        )
        body = build_unexpected_body(
            process_data,
            error_message,
            attachments,
            retry_count=retry_count,
        )
        send_outlook_email(
            mail_config,
            subject=subject,
            body=body,
            attachments=attachments or None,
            logger=logger,
        )
        logger.info("Sent NAS failure email notification")
    except Exception as error:
        logger.error(f"Failed to send NAS failure email notification: {error}")


def _send_nas_validation_error_email(
    *,
    process_data: dict[str, str],
    error_message: str,
    downloaded_file: Path,
    screenshot_path: Path | None,
    logger: logging.Logger,
) -> None:
    try:
        mail_config = MailConfig.load(Path("config/mail.ini"))
        attachments = [
            path
            for path in (downloaded_file, screenshot_path)
            if path is not None and path.exists()
        ]
        validation_rows = [
            {
                "Downloaded File": downloaded_file.name,
                "Error Message": error_message,
            }
        ]
        subject = build_validation_subject(
            str(process_data.get("RequestId", "")).strip(),
            str(process_data.get("PolicyNumber", "")).strip(),
        )
        body = build_validation_body(
            process_data,
            validation_rows,
            attachments,
        )
        send_outlook_email(
            mail_config,
            subject=subject,
            body=body,
            attachments=attachments or None,
            logger=logger,
        )
        logger.info(
            "Sent NAS validation error email with workbook attachment: %s",
            downloaded_file,
        )
    except Exception as error:
        logger.error(f"Failed to send NAS validation error email: {error}")


def _should_pause_after_login(browser_config: dict) -> bool:
    env_value = _read_bool_env("PLAYWRIGHT_PAUSE_AFTER_LOGIN")
    if env_value is not None:
        return env_value
    return bool(browser_config.get("pause_after_login", False))


async def _pause_after_login_if_enabled(page, enabled: bool, logger: logging.Logger) -> None:
    if not enabled:
        return

    logger.info(
        "Playwright pause_after_login is enabled. "
        "Complete OTP/manual login steps, then resume Playwright to continue."
    )
    await page.pause()


async def run(
    request_type: str,
    action_type: str,
    request_id: str | None = None,
    user_id: str | None = None,
    request_user_ids: list[str] | None = None,
    use_database: bool = True,
) -> None:
    run_id = _make_run_id()
    logger = _init_logger(run_id=run_id, request_id=request_id)
    run_dir = _build_run_log_dir(run_id=run_id, request_id=request_id)
    request_user_ids = [str(item).strip() for item in (request_user_ids or []) if str(item).strip()]
    _ = request_user_ids
    process_key = _resolve_process_key(request_type=request_type, action_type=action_type)

    config = load_yaml_file("config/base.yml")
    login_selectors = load_section_from_yaml("locators/nas/main/login_page.yml", section="login")
    new_button_selectors = load_section_from_yaml(
        "locators/nas/main/new_button_page.yml",
        section="new_button_page",
    )
    request_dashboard_selectors = load_section_from_yaml(
        "locators/nas/main/request_dashboard_page.yml",
        section="request_dashboard_page",
    )
    accordion_selectors = load_section_from_yaml(
        "locators/nas/main/accordion_page.yml",
        section="accordion_page",
    )
    bulk_add_member_selectors = load_section_from_yaml(
        "locators/nas/add_process/bulk_add_member.yml",
        section="bulk_add_member",
    )
    login_values = load_json_file("config/json_values/nas_login.json")
    add_member_values = load_json_file("config/json_values/nas_add_member.json")
    login_values["username"] = os.getenv("NAS_USERNAME", login_values.get("username", ""))
    login_values["password"] = os.getenv("NAS_PASSWORD", login_values.get("password", ""))

    if use_database:
        selector = load_process_selector(
            portal_name="NAS",
            request_id=request_id,
            user_id=user_id,
            logger=logger,
        )
        request_type = selector["RequestType"]
        action_type = selector["ActionType"]
        request_id = selector.get("RequestId") or request_id
        process_key = _resolve_process_key(request_type=request_type, action_type=action_type)

        db_result = load_member_process_values(
            portal_name="NAS",
            request_type=request_type,
            action_type=action_type,
            process_key=process_key,
            request_id=request_id,
            user_id=user_id if process_key in {"add_individual", "delete_manual"} else None,
            logger=logger,
        )
        request_id = db_result.request_id
        add_member_values = _merge_values(add_member_values, db_result.process_values)
        run_dir = _build_run_log_dir(run_id=run_id, request_id=request_id)
        logger = _init_logger(run_id=run_id, request_id=request_id)
        logger.info(
            "NAS database row loaded | "
            f"RequestId={db_result.request_id} | ActionType={action_type} | ProcessKey={process_key}"
        )

    if process_key in {"add_batch", "delete_batch", "delete_bulk"}:
        upload_paths = get_upload_paths("NAS", request_type, action_type)
        if not upload_paths:
            raise ValueError(
                f"NAS upload path mapping is missing for {request_type} {action_type}"
            )

        if process_key == "add_batch":
            env_bulk_file = str(os.getenv("NAS_BULK_MEMBER_FILE") or "").strip()
            if env_bulk_file:
                upload_paths["batch_member_file"] = env_bulk_file
                logger.info("Using NAS_BULK_MEMBER_FILE override: %s", env_bulk_file)
            elif use_database:
                result = build_nas_addition_census_file(
                    request_id=str(request_id or ""),
                    output_path=upload_paths["batch_member_file"],
                    include_user_ids=request_user_ids or None,
                    logger=logger,
                )
                logger.info(
                    "NAS addition census ready before portal start | "
                    "Template=%s | Members=%s | Output=%s",
                    result.template_path,
                    result.members_count,
                    result.output_path,
                )

            add_member_values = _merge_values(add_member_values, upload_paths)

            source_email_filename = None
            if request_id:
                source_email_filename = load_latest_request_email_filename(
                    request_id=str(request_id),
                    logger=logger,
                )
            resolved_payer_name = resolve_payer_name_from_email_filename(
                source_email_filename
            )
            if resolved_payer_name:
                add_member_values["resolved_payer_name"] = resolved_payer_name
                logger.info(
                    "NAS bulk payer resolved from source email | RequestId=%s | Payer=%s",
                    request_id,
                    resolved_payer_name,
                )
            else:
                logger.warning(
                    "NAS bulk payer could not be resolved from source email; "
                    "using configured payer | RequestId=%s | FileName=%s",
                    request_id,
                    source_email_filename or "-",
                )
        elif use_database:
            result = build_nas_deletion_census_file(
                request_id=str(request_id or ""),
                output_path=upload_paths["batch_delete_member_file"],
                include_user_ids=request_user_ids or None,
                logger=logger,
            )
            logger.info(
                "NAS deletion census ready before portal start | "
                "Template=%s | Members=%s | Output=%s",
                result.template_path,
                result.members_count,
                result.output_path,
            )

    paths_config = config.get("paths", {}) if isinstance(config, dict) else {}
    nas_login_url = str(paths_config.get("nas_login_url") or DEFAULT_NAS_LOGIN_URL).strip()

    browser_config = config.get("browser", {}) if isinstance(config, dict) else {}
    headless = bool(browser_config.get("headless", False))
    pause_after_login = _should_pause_after_login(browser_config)
    persistent_context = bool(browser_config.get("persistent_context", True))
    user_data_dir = Path(
        str(browser_config.get("nas_user_data_dir") or "data/browser_profiles/nas")
    )
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

    logger.info(
        "Starting NAS login flow | RequestId=%s | RequestType=%s | ActionType=%s",
        request_id or "-",
        request_type,
        action_type,
    )
    logger.info(f"Opening NAS login URL: {nas_login_url}")

    page = None
    browser = None
    async with async_playwright() as playwright:
        context = None
        trace_started = False
        try:
            if persistent_context:
                user_data_dir.mkdir(parents=True, exist_ok=True)
                if runtime_engine == "chromium":
                    context = await playwright.chromium.launch_persistent_context(
                        user_data_dir=str(user_data_dir.resolve()),
                        headless=headless,
                        channel=browser_channel,
                        viewport={"width": width, "height": height},
                    )
                elif runtime_engine == "firefox":
                    context = await playwright.firefox.launch_persistent_context(
                        user_data_dir=str(user_data_dir.resolve()),
                        headless=headless,
                        viewport={"width": width, "height": height},
                    )
                elif runtime_engine == "webkit":
                    context = await playwright.webkit.launch_persistent_context(
                        user_data_dir=str(user_data_dir.resolve()),
                        headless=headless,
                        viewport={"width": width, "height": height},
                    )
                else:
                    raise ValueError(f"Unsupported browser engine: {browser_engine}")
                logger.info(f"Using persistent NAS browser profile: {user_data_dir}")
            else:
                if runtime_engine == "chromium":
                    browser = await playwright.chromium.launch(headless=headless, channel=browser_channel)
                elif runtime_engine == "firefox":
                    browser = await playwright.firefox.launch(headless=headless)
                elif runtime_engine == "webkit":
                    browser = await playwright.webkit.launch(headless=headless)
                else:
                    raise ValueError(f"Unsupported browser engine: {browser_engine}")
                context = await browser.new_context(viewport={"width": width, "height": height})

            await context.tracing.start(
                screenshots=True,
                snapshots=True,
                sources=True,
            )
            trace_started = True
            logger.info("NAS Playwright tracing started")

            page = await context.new_page()
            await page.goto(nas_login_url, wait_until="domcontentloaded")

            await login(
                page=page,
                login_values=login_values,
                login_selectors=login_selectors,
                logger=logger,
            )

            await _pause_after_login_if_enabled(page, pause_after_login, logger)

            await open_new_member_page(
                page=page,
                selectors=new_button_selectors,
                logger=logger,
            )

            await open_request_dashboard_page(
                page=page,
                selectors=request_dashboard_selectors,
                process_key=process_key,
                logger=logger,
            )

            if process_key == "add_individual":
                await select_company_accordion(
                    page=page,
                    selectors=accordion_selectors,
                    values=add_member_values,
                    logger=logger,
                )
                await select_sub_policy_add_member(
                    page=page,
                    selectors=accordion_selectors,
                    values=add_member_values,
                    logger=logger,
                )
            elif process_key == "add_batch":
                await run_bulk_add_member(
                    page=page,
                    selectors=bulk_add_member_selectors,
                    values=add_member_values,
                    download_dir=run_dir,
                    logger=logger,
                )

        except Exception as exc:
            logger.error(f"NAS login flow failed: {exc}")
            error_shots = []
            if page is not None:
                try:
                    error_shot = run_dir / "nas_login_error.png"
                    await page.screenshot(path=str(error_shot), full_page=True)
                    logger.info(f"Saved NAS login error screenshot: {error_shot}")
                    error_shots.append(error_shot)
                except Exception as shot_exc:
                    logger.error(f"Failed to save NAS login error screenshot: {shot_exc}")
            failure_process_data = _build_mail_process_data(
                request_id=request_id,
                policy_number=_resolve_policy_number(add_member_values),
                action_type=action_type,
                status=(
                    "Validation Error"
                    if isinstance(exc, NasBulkValidationDownloadError)
                    else "Network or Loading Issue"
                ),
            )
            if isinstance(exc, NasBulkValidationDownloadError):
                _send_nas_validation_error_email(
                    process_data=failure_process_data,
                    error_message=str(exc),
                    downloaded_file=exc.downloaded_file,
                    screenshot_path=error_shots[0] if error_shots else None,
                    logger=logger,
                )
            else:
                _send_nas_error_email(
                    process_data=failure_process_data,
                    error_message=str(exc),
                    screenshot_paths=error_shots,
                    logger=logger,
                )
            raise
        finally:
            if context is not None and trace_started:
                trace_path = run_dir / "nas_playwright_trace.zip"
                try:
                    await context.tracing.stop(path=str(trace_path))
                    logger.info(f"Saved NAS Playwright trace: {trace_path}")
                except Exception as trace_exc:
                    logger.error(f"Failed to save NAS Playwright trace: {trace_exc}")
            if context is not None:
                await context.close()
            if browser is not None:
                await browser.close()

