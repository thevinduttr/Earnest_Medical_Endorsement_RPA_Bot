from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Mapping, Sequence


def _safe(value: object) -> str:
    return escape(str(value or ""), quote=True)


def _format_kv_table(items: Sequence[tuple[str, object]]) -> str:
    rows = "".join(
        f"""
            <tr>
                <td style=\"padding: 8px 12px; border: 1px solid #d6d6d6; font-weight: 700; width: 220px;\">{_safe(label)}</td>
                <td style=\"padding: 8px 12px; border: 1px solid #d6d6d6;\">{_safe(value)}</td>
            </tr>
        """
        for label, value in items
    )
    return f"<table style=\"border-collapse: collapse; width: 100%; max-width: 760px;\">{rows}</table>"


def _format_rows_table(rows: Sequence[Mapping[str, object]]) -> str:
    if not rows:
        return (
            "<table style=\"border-collapse: collapse; width: 100%; max-width: 760px;\">"
            "<tr><td style=\"padding: 8px 12px; border: 1px solid #d6d6d6;\">No records found.</td></tr>"
            "</table>"
        )

    columns = list(rows[0].keys())
    header_html = "".join(
        f"<th style=\"padding: 8px 12px; border: 1px solid #d6d6d6; text-align: left; background: #f3f4f6;\">{_safe(column)}</th>"
        for column in columns
    )
    body_html = ""
    for row in rows:
        body_html += "<tr>" + "".join(
            f"<td style=\"padding: 8px 12px; border: 1px solid #d6d6d6;\">{_safe(row.get(column, ''))}</td>"
            for column in columns
        ) + "</tr>"

    return f"""
        <table style="border-collapse: collapse; width: 100%; max-width: 980px;">
            <tr>{header_html}</tr>
            {body_html}
        </table>
    """


def _format_screenshot_list(screenshot_paths: Sequence[Path | str] | None) -> str:
    screenshot_rows = "".join(f"<li>{_safe(Path(path).name)}</li>" for path in screenshot_paths or [])
    return screenshot_rows or "<li>No screenshots attached.</li>"


def build_validation_subject(request_number: str, policy_number: str) -> str:
    return (
        f"RequestNumber : {request_number} - PolicyNumber : {policy_number} - "
        "Status : Validation Error"
    )


def build_unexpected_subject(request_number: str, policy_number: str) -> str:
    return (
        f"RequestNumber : {request_number} - PolicyNumber : {policy_number} - "
        "Status : Network or Loading Issue"
    )


def build_validation_body(
    process_data: Mapping[str, object],
    invalid_rows: Sequence[Mapping[str, object]],
    attachment_paths: Sequence[Path | str] | None = None,
) -> str:
    request_number = str(process_data.get("RequestId", "")).strip()
    policy_number = str(process_data.get("PolicyNumber", "")).strip()
    action_type = str(process_data.get("ActionType", "")).strip()
    portal_name = str(process_data.get("PortalName", "")).strip()

    return f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #1f2937; line-height: 1.5;">
            <div style="max-width: 980px; margin: 0 auto; padding: 16px;">
                <h2 style="margin: 0 0 12px; color: #b91c1c;">Validation Error</h2>
                <p>The batch validation found invalid member rows. Review the table below and correct the source data.</p>
                <h3 style="margin: 24px 0 12px; color: #111827;">Process Details</h3>
                {_format_kv_table([
                    ("Request Number", request_number),
                    ("Policy Number", policy_number),
                    ("Action Type", action_type),
                    ("Portal Name", portal_name),
                    ("Status", "Validation Error"),
                ])}
                <h3 style="margin: 24px 0 12px; color: #111827;">Validation Errors</h3>
                {_format_rows_table(invalid_rows)}
                <h3 style="margin: 24px 0 12px; color: #111827;">Validation Attachments</h3>
                <p>Review the attached validation workbook and/or portal screenshot for further details.</p>
                <h3 style="margin: 24px 0 12px; color: #111827;">Attached Files</h3>
                <ul>
                    {_format_screenshot_list(attachment_paths)}
                </ul>
            </div>
        </body>
    </html>
    """


def build_unexpected_body(
    process_data: Mapping[str, object],
    error_message: str,
    screenshot_paths: Sequence[Path | str] | None = None,
    retry_count: int = 3,
) -> str:
    request_number = str(process_data.get("RequestId", "")).strip()
    policy_number = str(process_data.get("PolicyNumber", "")).strip()
    action_type = str(process_data.get("ActionType", "")).strip()
    portal_name = str(process_data.get("PortalName", "")).strip()

    return f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #1f2937; line-height: 1.5;">
            <div style="max-width: 820px; margin: 0 auto; padding: 16px;">
                <h2 style="margin: 0 0 12px; color: #b91c1c;">Network or Loading Issue</h2>
                <p>An unexpected issue occurred during the portal run after {retry_count} retry attempts.</p>
                <h3 style="margin: 24px 0 12px; color: #111827;">Process Details</h3>
                {_format_kv_table([
                    ("Request Number", request_number),
                    ("Policy Number", policy_number),
                    ("Action Type", action_type),
                    ("Portal Name", portal_name),
                    ("Status", "Network or Loading Issue"),
                ])}
                <h3 style="margin: 24px 0 12px; color: #111827;">Error Details</h3>
                {_format_kv_table([
                    ("Error Message", error_message),
                    ("Retry Attempts", str(retry_count)),
                ])}
                <h3 style="margin: 24px 0 12px; color: #111827;">Attached Screenshots</h3>
                <ul>
                    {_format_screenshot_list(screenshot_paths)}
                </ul>
            </div>
        </body>
    </html>
    """


def _format_process_details(process_data: Mapping[str, object]) -> str:
    request_id = str(process_data.get("RequestId", "")).strip()
    action_type = str(process_data.get("ActionType", "")).strip()
    portal_name = str(process_data.get("PortalName", "")).strip()
    reference_number = str(process_data.get("ReferenceNumber", "")).strip()
    policy_number = str(process_data.get("PolicyNumber", "")).strip()
    items: list[tuple[str, object]] = [
        ("RequestId", request_id),
        ("ActionType", action_type),
        ("PortalName", portal_name),
        ("ReferenceNumber", reference_number),
        ("PolicyNumber", policy_number),
    ]
    processed_members = process_data.get("ProcessedMembers")
    if processed_members is not None:
        items.append(("Processed Members", processed_members))
    return _format_kv_table(items)


def _format_extracted_data(process_data: Mapping[str, object]) -> str:
    endorsement_number = str(process_data.get("endorsement_number", "")).strip()
    insured_details = process_data.get("insured_details") or []

    insured_rows = ""
    for index, insured in enumerate(insured_details, 1):
        employee_number = str(insured.get("Employee Number", "")).strip()
        card_number = str(insured.get("Card Number", "")).strip()
        name = str(insured.get("Name", "")).strip()
        insured_rows += f"""
            <tr>
                <td style="padding: 8px 12px; border: 1px solid #d6d6d6;">{_safe(index)}</td>
                <td style="padding: 8px 12px; border: 1px solid #d6d6d6;">{_safe(employee_number)}</td>
                <td style="padding: 8px 12px; border: 1px solid #d6d6d6;">{_safe(card_number)}</td>
                <td style="padding: 8px 12px; border: 1px solid #d6d6d6;">{_safe(name)}</td>
            </tr>
        """

    if not insured_rows:
        insured_rows = """
            <tr>
                <td colspan="4" style="padding: 8px 12px; border: 1px solid #d6d6d6;">No insured details were extracted.</td>
            </tr>
        """

    return f"""
        <table style="border-collapse: collapse; width: 100%; max-width: 760px; margin-bottom: 16px;">
            <tr>
                <td style="padding: 8px 12px; border: 1px solid #d6d6d6; font-weight: 700; width: 220px;">Endorsement Number</td>
                <td style="padding: 8px 12px; border: 1px solid #d6d6d6;">{_safe(endorsement_number)}</td>
            </tr>
        </table>
        <table style="border-collapse: collapse; width: 100%; max-width: 760px;">
            <tr>
                <th style="padding: 8px 12px; border: 1px solid #d6d6d6; text-align: left; background: #f3f4f6;">#</th>
                <th style="padding: 8px 12px; border: 1px solid #d6d6d6; text-align: left; background: #f3f4f6;">Employee Number</th>
                <th style="padding: 8px 12px; border: 1px solid #d6d6d6; text-align: left; background: #f3f4f6;">Card Number</th>
                <th style="padding: 8px 12px; border: 1px solid #d6d6d6; text-align: left; background: #f3f4f6;">Name</th>
            </tr>
            {insured_rows}
        </table>
    """


def build_success_subject(process_data: Mapping[str, object]) -> str:
    request_id = str(process_data.get("RequestId", "")).strip()
    policy_number = str(process_data.get("PolicyNumber", "")).strip()
    status = (
        "Test Review Completed"
        if process_data.get("SubmissionSkipped")
        else "Addion Completed"
    )
    return f"RequestNumber : {request_id} - PolicyNumber : {policy_number} - Status : {status}"


def build_success_body(process_data: Mapping[str, object], attachments: Sequence[Path] | None = None) -> str:
    attachment_rows = "".join(f"<li>{_safe(Path(path).name)}</li>" for path in (attachments or []))
    screenshot_paths = process_data.get("screenshots") or []
    screenshot_rows = "".join(f"<li>{_safe(Path(path).name)}</li>" for path in screenshot_paths)
    if not screenshot_rows:
        screenshot_rows = "<li>No screenshots attached.</li>"
    has_reference = bool(str(process_data.get("ReferenceNumber", "")).strip())
    submission_skipped = bool(process_data.get("SubmissionSkipped"))
    if submission_skipped:
        heading = "NAS Test Review Completed"
        completion_message = (
            "The NAS member review completed successfully. Member Submit clicks "
            "were skipped because test mode is enabled."
        )
    else:
        heading = "Addition Completed"
        completion_message = (
            "The batch addition completed successfully and the submission reference number was captured."
            if has_reference
            else "The batch addition completed successfully."
        )
    extracted_data = ""
    if process_data.get("endorsement_number") or process_data.get("insured_details"):
        extracted_data = f"""
                <h3 style="margin: 24px 0 12px; color: #111827;">Extracted Data</h3>
                {_format_extracted_data(process_data)}
        """

    return f"""
    <html>
        <body style="font-family: Arial, sans-serif; color: #1f2937; line-height: 1.5;">
            <div style="max-width: 820px; margin: 0 auto; padding: 16px;">
                <h2 style="margin: 0 0 12px; color: #0f766e;">{heading}</h2>
                <p>{completion_message}</p>
                <h3 style="margin: 24px 0 12px; color: #111827;">Process Details</h3>
                {_format_process_details(process_data)}
                {extracted_data}
                <h3 style="margin: 24px 0 12px; color: #111827;">Attached Documents</h3>
                <ul>
                    {attachment_rows}
                </ul>
                <h3 style="margin: 24px 0 12px; color: #111827;">Attached Screenshots</h3>
                <ul>
                    {screenshot_rows}
                </ul>
            </div>
        </body>
    </html>
    """
