"""Human-reported SRP entry and submission timestamps."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def submission_key(report_type: str, stage: str) -> str:
    return f"{report_type}_{stage}"


def current_submission(case: dict) -> dict:
    srp = case.get("srp", {})
    key = submission_key(srp.get("type", "AEV"), srp.get("stage", "EW"))
    return dict(case.get("srp_submissions", {}).get(key, {}))


def submission_state(record: dict, evidence_rows: list[dict] | None = None) -> dict:
    submitted = record.get("submission_status") == "submitted_unverified"
    required = (
        record.get("entry_completed_at"),
        record.get("entry_timezone"),
        record.get("submitted_at"),
        record.get("submitted_timezone"),
        record.get("reference_number"),
        record.get("receipt_evidence_id"),
    )
    receipt_exists = bool(str(record.get("receipt_evidence_id", "")).strip())
    if evidence_rows is not None:
        receipt_exists = any(
            item.get("evidence_id") == record.get("receipt_evidence_id")
            for item in evidence_rows
        )
    if submitted and all(str(value or "").strip() for value in required) and receipt_exists:
        return {
            "key": "confirmed",
            "label": "提交紀錄齊備（提交為人員回報；D7 回執索引已連結）",
            "confirmed": True,
        }
    if submitted:
        return {"key": "unverified", "label": "已回報提交，待補齊提交證據", "confirmed": False}
    if record.get("entry_completed_at"):
        return {"key": "not-submitted", "label": "欄位已填，尚未正式提交", "confirmed": False}
    return {"key": "pending", "label": "等待 SRP 人員回報", "confirmed": False}


def format_report_time(local_value: str, timezone_name: str) -> str:
    if not local_value:
        return ""
    try:
        value = datetime.fromisoformat(local_value)
        zone = ZoneInfo(timezone_name or "Asia/Taipei")
    except (ValueError, ZoneInfoNotFoundError):
        return local_value
    if value.tzinfo is None:
        value = value.replace(tzinfo=zone)
    else:
        value = value.astimezone(zone)
    return value.strftime("%Y-%m-%d %H:%M %Z")


def all_submissions(case: dict) -> list[tuple[str, dict]]:
    records = case.get("srp_submissions", {})
    result = [(key, dict(value)) for key, value in records.items()]
    return sorted(result, key=lambda item: item[0])

