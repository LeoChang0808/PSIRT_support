from __future__ import annotations

import io
import os
import re
import secrets
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import (
    Flask, abort, flash, jsonify, make_response, redirect, render_template,
    request, send_file, session, url_for,
)

from forms import (
    D7_TEMPLATE_FILE, TEMPLATE_FILES, evidence_references, load_form_schema,
    shared_field_key,
)
from report_pdf import STAGE_LABELS, build_srp_pdf
from storage import EncryptedCaseStore
from submission import current_submission, submission_key, submission_state
from srp_fields import (
    ENISA_GLOSSARY_CHECKED, ENISA_GLOSSARY_UPDATED, ENISA_GLOSSARY_URL,
    SRP_PLATFORM_UPDATED, SRP_PLATFORM_VERSION, build_srp_fields,
)
from time_utils import deadline_iso, deadline_display
from xlsx_export import build_xlsx

APP_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = Path(os.environ.get("PSIRT_TEMPLATE_DIR", APP_DIR / "form")).expanduser()
DATA_DIR = Path(os.environ.get("PSIRT_DATA_DIR", APP_DIR / ".data")).expanduser()
DATABASE_PATH = DATA_DIR / "cases.sqlite3.enc"

STEP_ORDER = ("7.1", "7.2", "7.3", "7.4", "7.5", "7.6", "7.7", "7.8", "7.9")
STEP_TITLES = {
    "7.1": "接收漏洞／資安事件資訊",
    "7.2": "確認產品與 CRA 適用性",
    "7.3": "判定 Article 14 通報義務",
    "7.4": "啟動通報與期限管理",
    "7.5": "提交 24 小時 Early Warning",
    "7.6": "提交 72 小時 Notification",
    "7.7": "通知受影響使用者（平行作業）",
    "7.8": "後續追蹤與 CSIRT 中間報告",
    "7.9": "最終報告、期限確認與歸檔",
}
STEP_SHORT_TITLES = {
    "7.1": "收案",
    "7.2": "產品適用",
    "7.3": "通報判定",
    "7.4": "期限管理",
    "7.5": "24h 預警",
    "7.6": "72h 通報",
    "7.7": "使用者通知",
    "7.8": "中間報告",
    "7.9": "最終結案",
}
STEP_HELP = {
    "7.1": "登錄來源、首次接收時間、初始描述、產品線索與承辦人；收案時間不自動等同 Awareness Time。",
    "7.2": "確認產品、版本、數位元素、歐盟市場與 CRA 適用性，補充影響產品及使用者範圍。",
    "7.3": "整理利用證據、Article 14 條件、通報判定與核准依據；通報類型由權責人員確認。",
    "7.4": "記錄經核准的 Awareness Time、指定 CSIRT／SRP 代表與期限安排；右側顯示 24／72 小時倒數。",
    "7.5": "準備 24 小時 Early Warning。下載 SRP PDF 後由人員手動填寫 SRP，再回報填寫與提交時間。",
    "7.6": "更新 72 小時 Notification 的技術影響、緩解措施與未知事項；SRP 仍由人員手動操作。",
    "7.7": "此步驟與 7.5、7.6 平行啟動，不等待修補或前述提交；記錄通知對象、措施與送達證據。",
    "7.8": "持續更新調查與使用者通知；僅在 CSIRT 明確要求時勾選並準備 Intermediate Report。",
    "7.9": "完成最終報告、期限與結案核對，整理 Evidence 索引；全部步驟完成後統一匯出 D1–D7。",
}
FORM_TITLES = {
    "D1": "產品與 CRA 適用性清冊",
    "D2": "漏洞與資安事件接收登錄表",
    "D3": "產品資安影響與通報條件評估表",
    "D4": "法規通報決策與期限追蹤表",
    "D5": "SRP 法規通報提交紀錄表",
    "D6": "受影響使用者通知與資安公告表",
}
WORKFLOW_FIELDS = {
    "7.1": (("D2", (13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 26, 27)),),
    "7.2": (
        ("D1", (13, 14, 15, 17, 18, 19, 20, 21, 23, 24, 25)),
        ("D2", (24, 25)),
        ("D3", (13, 15, 16, 17, 18)),
    ),
    "7.3": (
        ("D3", (20, 21, 22, 24, 25, 26, 28, 29, 30, 34)),
        ("D4", (13, 14, 15, 16, 17)),
    ),
    "7.4": (
        ("D1", (27, 28, 29, 30, 31, 32, 33, 34, 36)),
        ("D3", (32,)),
        ("D4", (25, 27, 28, 30, 31)),
    ),
    "7.5": (("D5", (13, 14, 15, 16, 17, 19, 20, 21, 22, 23, 24, 25)),),
    "7.6": (
        ("D3", (37, 38)),
        ("D4", (22, 23)),
        ("D5", (27, 28, 29, 30, 31, 32)),
    ),
    "7.7": (("D6", (13, 14, 15, 16, 18, 19, 20, 21, 22, 23, 24, 25)),),
    "7.8": (
        ("D3", (36,)),
        ("D4", (33, 34)),
        ("D5", (34, 35, 36)),
        ("D6", (27, 28, 29, 31, 33)),
    ),
    "7.9": (
        ("D3", (39, 40)),
        ("D4", (24, 35)),
        ("D5", (38, 39, 40, 41, 43)),
    ),
}
LEGACY_STEP_MAP = {
    "D2": "7.1",
    "D1": "7.2",
    "D3": "7.3",
    "D4": "7.4",
    "SRP": "7.5",
    "D5": "7.6",
    "D6": "7.7",
    "D7": "7.9",
}
REPORT_STAGE_BY_STEP = {
    "7.5": "EW",
    "7.6": "72h",
    "7.9": "Final",
}

D7_REVIEW_FIELDS = (
    (35, "原始檔案完整性／校驗方式（適用時）"),
    (36, "存取／保管權限"),
    (37, "相關 D1～D6 的 Case ID 一致性"),
    (38, "證據編號重複／遺漏檢查結果"),
    (39, "證據版本及更動紀錄"),
    (40, "主管機關通報提交證據核對"),
    (41, "使用者通知／發布證據核對"),
    (42, "法規通報結案／內部歸檔狀態"),
    (43, "保管單位／複核人／複核時間"),
)

SCHEMA, MISSING_TEMPLATES = load_form_schema(TEMPLATE_DIR)
if not (TEMPLATE_DIR / D7_TEMPLATE_FILE).exists():
    MISSING_TEMPLATES.append(D7_TEMPLATE_FILE)
STORE = EncryptedCaseStore(DATABASE_PATH)

app = Flask(__name__)
app.secret_key = os.environ.get("PSIRT_SESSION_SECRET") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)


@app.before_request
def _ensure_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)


def _check_csrf() -> None:
    expected = session.get("csrf_token", "")
    supplied = request.headers.get("X-CSRF-Token", "")
    if request.is_json:
        supplied = request.json.get("csrf_token", supplied) if request.json else supplied
    else:
        supplied = request.form.get("csrf_token", supplied)
    if not expected or not secrets.compare_digest(expected, supplied):
        abort(400, description="表單安全憑證已失效，請重新載入頁面。")


def _local_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="minutes")


def _new_case() -> dict:
    now = _local_now()
    case_number = STORE.next_case_number(datetime.now().astimezone().year)
    return {
        "id": secrets.token_urlsafe(18),
        "case_number": case_number,
        "title": "新案件",
        "created_at": now,
        "updated_local": now,
        "current_step": "7.1",
        "steps": {step: "not_started" for step in STEP_ORDER},
        "forms": {code: {} for code in TEMPLATE_FILES},
        "shared_fields": {
            "case_id": {
                "value": case_number,
                "source_step": "系統",
                "source_label": "自動產生的 Case ID",
                "updated_at": now,
            }
        },
        "awareness": {"local": "", "timezone": "Asia/Taipei"},
        "srp": {"type": "AEV", "stage": "EW", "intermediate_requested": False},
        "srp_submissions": {},
        "evidence_meta": {"custodian": "", "location": "", "review": {}},
        "evidence": [],
        "events": [],
    }


def _migrate_case_workflow(case: dict) -> bool:
    """Map the old D1-D7 navigation onto procedure 7.1-7.9 without touching form data."""
    old_steps = case.get("steps", {})
    inverse = {}
    for old_step, new_step in LEGACY_STEP_MAP.items():
        inverse.setdefault(new_step, []).append(old_step)
    new_steps = {}
    valid_statuses = {"not_started", "in_progress", "completed"}
    for step in STEP_ORDER:
        status = old_steps.get(step)
        if status not in valid_statuses:
            status = next(
                (old_steps.get(old) for old in inverse.get(step, ())
                 if old_steps.get(old) in valid_statuses),
                "not_started",
            )
        new_steps[step] = status
    changed = new_steps != old_steps
    if changed:
        case["steps"] = new_steps

    old_current = case.get("current_step", "")
    current = LEGACY_STEP_MAP.get(old_current, old_current)
    if current not in STEP_ORDER:
        current = "7.1"
    if current != old_current:
        case["current_step"] = current
        changed = True
    return changed


def _case_or_404(case_id: str) -> dict:
    case = STORE.get(case_id)
    if case is None or case.get("trashed_at"):
        abort(404)
    if _migrate_case_workflow(case):
        STORE.save(case)
    return case

def _record_event(case: dict, event: str) -> None:
    case.setdefault("events", []).append({
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "event": event,
    })
    case["events"] = case["events"][-100:]
    case["updated_local"] = _local_now()


def _field_value(case: dict, code: str, field: dict, name: str) -> str:
    stored = case.get("forms", {}).get(code, {}).get(str(field["row"]), {})
    value = stored.get(name, "")
    if value:
        return str(value)
    if name == "entry":
        shared = case.get("shared_fields", {}).get(shared_field_key(field["label"]), "")
        if isinstance(shared, dict):
            shared = shared.get("value", "")
        return str(shared)
    return ""


def _uses_datetime_picker(field: dict) -> bool:
    label = str(field.get("label", "")).casefold()
    return (
        any(marker in label for marker in ("時間", "日期"))
        or bool(re.search(r"\b(date|time|timestamp|deadline)\b", label))
    )


def _datetime_local_value(value: object) -> str:
    """Convert a stored local timestamp to the browser datetime-local format."""
    raw = str(value or "").strip()
    match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::\d{2})?", raw
    )
    return f"{match.group(1)}T{match.group(2)}" if match else ""


def _apply_template_fields(
    case: dict, code: str, values: dict, allowed_rows: tuple[int, ...] | None = None,
) -> None:
    section = case.setdefault("forms", {}).setdefault(code, {})
    shared_fields = case.setdefault("shared_fields", {})
    allowed = set(allowed_rows) if allowed_rows is not None else None
    for field in SCHEMA.get(code, []):
        row = str(field["row"])
        if allowed is not None and int(row) not in allowed:
            continue
        label = field["label"]
        special_time = code == "D4" and int(row) in {19, 20, 21}
        if special_time:
            continue
        current = dict(section.get(row, {}))
        changed = False
        for part in ("entry", "note", "evidence_id"):
            name = f"field__{code}__{row}__{part}"
            legacy_name = f"field__{row}__{part}"
            if name in values or legacy_name in values:
                current[part] = str(values.get(name, values.get(legacy_name, ""))).strip()
                changed = True
        timezone_name = f"field__{code}__{row}__timezone"
        legacy_timezone_name = f"field__{row}__timezone"
        if timezone_name in values or legacy_timezone_name in values:
            current["timezone"] = str(
                values.get(timezone_name, values.get(legacy_timezone_name, ""))
            ).strip()
            changed = True
        if changed:
            section[row] = current
        entry = section.get(row, {}).get("entry", "").strip()
        if entry:
            key = shared_field_key(label)
            existing = shared_fields.get(key, "")
            existing_value = existing.get("value", "") if isinstance(existing, dict) else existing
            if existing_value != entry:
                shared_fields[key] = {
                    "value": entry,
                    "source_step": code,
                    "source_label": label,
                    "updated_at": _local_now(),
                }
        if code == "D2" and "案件標題" in label and entry:
            case["title"] = entry
        if shared_field_key(label) == "case_id" and entry:
            case["case_number"] = entry

def _apply_evidence(case: dict, values: dict) -> None:
    metadata = case.setdefault("evidence_meta", {})
    for key in ("custodian", "location"):
        if f"evidence_meta__{key}" in values:
            metadata[key] = str(values.get(f"evidence_meta__{key}", "")).strip()
    review = metadata.setdefault("review", {})
    for row, _label in D7_REVIEW_FIELDS:
        if row == 43:
            for suffix, target in (("details", "43_details"), ("at", "43_at"),
                                   ("timezone", "43_timezone")):
                key = f"d7_review__43_{suffix}"
                if key in values:
                    review[target] = str(values.get(key, "")).strip()
        else:
            key = f"d7_review__{row}"
            if key in values:
                review[str(row)] = str(values.get(key, "")).strip()

    grouped: dict[int, dict] = {}
    pattern = re.compile(r"evidence__(\d+)__(evidence_id|obtained_at|timezone|kind|description|source|location|custodian)")
    for name, value in values.items():
        match = pattern.fullmatch(name)
        if match:
            grouped.setdefault(int(match.group(1)), {})[match.group(2)] = str(value).strip()
    evidence = []
    for index in sorted(grouped):
        record = grouped[index]
        if any(str(value).strip() for value in record.values()):
            evidence.append(record)
    case["evidence"] = evidence


def _apply_srp(case: dict, values: dict) -> None:
    srp = case.setdefault("srp", {})
    if "srp_type" in values:
        srp["type"] = values.get("srp_type") if values.get("srp_type") in {"AEV", "SI"} else "AEV"
    if "srp_stage" in values:
        requested = str(values.get("intermediate_requested", "")).lower() in {"1", "true", "on", "yes"}
        stage = str(values.get("srp_stage", "EW"))
        if stage == "Intermediate" and not requested:
            stage = "EW"
        if stage in STAGE_LABELS:
            srp["stage"] = stage
        srp["intermediate_requested"] = requested
    elif "intermediate_requested" in values:
        srp["intermediate_requested"] = str(values.get("intermediate_requested", "")).lower() in {
            "1", "true", "on", "yes"
        }


def _apply_srp_submission(case: dict, values: dict) -> str | None:
    key = submission_key(
        case.get("srp", {}).get("type", "AEV"),
        case.get("srp", {}).get("stage", "EW"),
    )
    records = case.setdefault("srp_submissions", {})
    record = dict(records.get(key, {}))
    mapping = {
        "srp_entry_completed_at": "entry_completed_at",
        "srp_entry_timezone": "entry_timezone",
        "srp_submission_status": "submission_status",
        "srp_submitted_at": "submitted_at",
        "srp_submitted_timezone": "submitted_timezone",
        "srp_reference_number": "reference_number",
        "srp_receipt_evidence_id": "receipt_evidence_id",
    }
    for source, target in mapping.items():
        if source in values:
            record[target] = str(values.get(source, "")).strip()
    for local_key, zone_key in (
        ("entry_completed_at", "entry_timezone"),
        ("submitted_at", "submitted_timezone"),
    ):
        local_value = record.get(local_key, "")
        timezone_name = record.get(zone_key, "Asia/Taipei")
        if local_value:
            try:
                datetime.fromisoformat(local_value)
                ZoneInfo(timezone_name)
            except (ValueError, ZoneInfoNotFoundError):
                return "SRP 時間或時區格式無效，請使用有效日期時間及 IANA 時區。"
    if record.get("submission_status") not in {"not_submitted", "submitted_unverified"}:
        record["submission_status"] = "not_submitted"
    records[key] = record
    return None


def _apply_awareness(case: dict, values: dict) -> str | None:
    local_value = str(values.get("awareness_local", "")).strip()
    timezone_name = str(values.get("awareness_timezone", "Asia/Taipei")).strip()
    if local_value:
        try:
            datetime.fromisoformat(local_value)
            ZoneInfo(timezone_name)
        except (ValueError, ZoneInfoNotFoundError):
            return "知悉時間或時區格式無效；請使用有效日期時間及 IANA 時區，例如 Asia/Taipei。"
    case["awareness"] = {"local": local_value, "timezone": timezone_name or "Asia/Taipei"}
    return None


def _set_report_stage(case: dict, step: str) -> None:
    stage = REPORT_STAGE_BY_STEP.get(step)
    if step == "7.8":
        stage = "Intermediate" if case.get("srp", {}).get("intermediate_requested") else "72h"
    if stage:
        case.setdefault("srp", {})["stage"] = stage


def _submission_for_step(case: dict, step: str) -> dict:
    stage = {
        "7.5": "EW",
        "7.6": "72h",
        "7.8": "Intermediate",
        "7.9": "Final",
    }.get(step)
    if not stage:
        return current_submission(case)
    report_type = case.get("srp", {}).get("type", "AEV")
    return dict(case.get("srp_submissions", {}).get(submission_key(report_type, stage), {}))


def _export_readiness(case: dict) -> dict:
    """Describe incomplete workflow fields for a non-blocking export reminder."""
    fields = []
    seen = set()

    def add_field(name: str, label: str, value: object, picker_name: str = "") -> None:
        fields.append({
            "name": name,
            "picker_name": picker_name,
            "label": label,
            "filled": bool(str(value or "").strip()),
        })

    for step in STEP_ORDER:
        for code, rows in WORKFLOW_FIELDS.get(step, ()):
            allowed = set(rows)
            for field in SCHEMA.get(code, []):
                row = int(field["row"])
                key = (code, row)
                if row not in allowed or key in seen:
                    continue
                seen.add(key)
                name = f"field__{code}__{row}__entry"
                picker_name = f"{name}-datetime" if _uses_datetime_picker(field) else ""
                add_field(
                    name, f"{code} · {field['label']}",
                    _field_value(case, code, field, "entry"), picker_name,
                )

    awareness = case.get("awareness", {})
    add_field("awareness_local", "D4 · Awareness Time", awareness.get("local", ""))
    add_field("awareness_timezone", "D4 · Awareness Time 時區", awareness.get("timezone", ""))

    evidence_meta = case.get("evidence_meta", {})
    for key, label in (("custodian", "證據保管權責人"), ("location", "受控證據保存位置／資料庫")):
        add_field(f"evidence_meta__{key}", f"D7 · {label}", evidence_meta.get(key, ""))

    review = evidence_meta.get("review", {})
    for row, label in D7_REVIEW_FIELDS:
        if row == 43:
            add_field(
                "d7_review__43_details", "D7 · 保管單位／複核人與補充資訊",
                review.get("43_details", review.get("43", "")),
            )
            add_field("d7_review__43_at", "D7 · 複核時間", review.get("43_at", ""))
            add_field("d7_review__43_timezone", "D7 · 複核時區", review.get("43_timezone", ""))
        else:
            add_field(f"d7_review__{row}", f"D7 · {label}", review.get(str(row), ""))

    evidence_fields = (
        ("evidence_id", "Evidence ID", ""),
        ("obtained_at", "取得時間", "_picker"),
        ("timezone", "時區", ""),
        ("kind", "證據類型", ""),
        ("description", "內容描述", ""),
        ("source", "來源", ""),
        ("location", "受控保存位置", ""),
        ("custodian", "保管人", ""),
    )
    evidence_items = case.get("evidence", [])
    if not evidence_items:
        add_field("evidence__none", "D7 · Evidence 索引", "")
    for index, item in enumerate(evidence_items):
        for key, label, picker_suffix in evidence_fields:
            name = f"evidence__{index}__{key}"
            picker_name = f"{name}{picker_suffix}" if picker_suffix else ""
            add_field(name, f"D7 · {item.get('evidence_id') or '證據'} · {label}", item.get(key, ""), picker_name)

    incomplete_steps = [
        {"code": step, "label": STEP_TITLES[step]}
        for step in STEP_ORDER
        if case.get("steps", {}).get(step) != "completed"
    ]
    return {"fields": fields, "incomplete_steps": incomplete_steps}


def _apply_step(case: dict, step: str, values: dict, intent: str) -> None:
    for code, rows in WORKFLOW_FIELDS.get(step, ()):
        _apply_template_fields(case, code, values, rows)

    if step in {"7.3", "7.8"}:
        _apply_srp(case, values)
    _set_report_stage(case, step)

    if step == "7.4" and "awareness_local" in values:
        error = _apply_awareness(case, values)
        if error:
            raise ValueError(error)

    if step == "7.9":
        _apply_evidence(case, values)

    tracks_submission = step in {"7.5", "7.6", "7.9"} or (
        step == "7.8" and case.get("srp", {}).get("intermediate_requested")
    )
    if tracks_submission:
        error = _apply_srp_submission(case, values)
        if error:
            raise ValueError(error)

    if intent == "complete":
        case.setdefault("steps", {})[step] = "completed"
    else:
        status = case.setdefault("steps", {}).get(step, "not_started")
        if status != "completed":
            case["steps"][step] = "in_progress" if any(
                str(value).strip() for key, value in values.items()
                if key not in {"csrf_token", "intent"}
            ) else status

    if intent in {"next", "complete"}:
        current_index = STEP_ORDER.index(step)
        if current_index < len(STEP_ORDER) - 1:
            case["current_step"] = STEP_ORDER[current_index + 1]
        else:
            case["current_step"] = step
    else:
        case["current_step"] = step
    _record_event(case, f"{step} 資料已保存")

def _render_fields(case: dict, step: str) -> list[dict]:
    fields: list[dict] = []
    for code, rows in WORKFLOW_FIELDS.get(step, ()):
        allowed = set(rows)
        for field in SCHEMA.get(code, []):
            if field["row"] not in allowed:
                continue
            if code == "D4" and field["row"] in {19, 20, 21}:
                continue
            label = field["label"]
            stored = case.get("forms", {}).get(code, {}).get(str(field["row"]), {})
            shared_record = case.get("shared_fields", {}).get(shared_field_key(label), "")
            if isinstance(shared_record, dict):
                reused_value = shared_record.get("value", "")
                source_step = shared_record.get("source_step", "")
                source_label = shared_record.get("source_label", label)
                source_updated = shared_record.get("updated_at", "")
            else:
                reused_value, source_step, source_label, source_updated = shared_record, "", label, ""
            local_value = stored.get("entry", "")
            entry_value = _field_value(case, code, field, "entry")
            datetime_picker = _uses_datetime_picker(field)
            picker_value = _datetime_local_value(entry_value) if datetime_picker else ""
            legacy_datetime_value = (
                entry_value if datetime_picker and entry_value and not picker_value else ""
            )
            timezone_value = stored.get("timezone", "")
            if not timezone_value and not legacy_datetime_value:
                timezone_value = case.get("awareness", {}).get("timezone", "Asia/Taipei")
            row = str(field["row"])
            fields.append({
                **field,
                "source_code": code,
                "source_title": FORM_TITLES[code],
                "dom_id": f"field-{code}-{row}",
                "entry_name": f"field__{code}__{row}__entry",
                "note_name": f"field__{code}__{row}__note",
                "evidence_name": f"field__{code}__{row}__evidence_id",
                "timezone_name": f"field__{code}__{row}__timezone",
                "entry": entry_value,
                "note": _field_value(case, code, field, "note"),
                "evidence_id": _field_value(case, code, field, "evidence_id"),
                "datetime_picker": datetime_picker,
                "datetime_value": picker_value,
                "legacy_datetime_value": legacy_datetime_value,
                "timezone_field": "時區" in label,
                "timezone_value": timezone_value,
                "reused": bool(reused_value) and (
                    not bool(local_value)
                    or (source_step and source_step != code and local_value == reused_value)
                ),
                "stale": bool(local_value and reused_value and local_value != reused_value),
                "reuse_source": source_step + " · " + source_label if source_step else "",
                "reuse_updated": source_updated,
            })
    return fields

def _render_case(case: dict, step: str):
    if step not in STEP_ORDER:
        step = case.get("current_step", "7.1")
    awareness = case.get("awareness", {})
    current_deadlines = {
        "24": deadline_iso(case, 24),
        "72": deadline_iso(case, 72),
    }
    deadline_labels = {
        "24": deadline_display(case, 24),
        "72": deadline_display(case, 72),
    }
    references_by_id = evidence_references(case, SCHEMA)
    evidence_items = []
    for item in case.get("evidence", []):
        obtained_at = str(item.get("obtained_at", ""))
        picker_value = _datetime_local_value(obtained_at)
        references = references_by_id.get(str(item.get("evidence_id", "")), [])
        evidence_items.append({
            **item,
            "obtained_at_picker": picker_value,
            "legacy_obtained_at": (
                obtained_at if obtained_at and not picker_value else ""
            ),
            "timezone": item.get("timezone") or awareness.get("timezone", "Asia/Taipei"),
            "references": references,
            "can_remove": not references,
        })
    submission_record = _submission_for_step(case, step)
    return render_template(
        "case.html",
        case=case,
        step=step,
        step_order=STEP_ORDER,
        step_titles=STEP_TITLES,
        step_short_titles=STEP_SHORT_TITLES,
        step_help=STEP_HELP,
        step_index=STEP_ORDER.index(step),
        fields=_render_fields(case, step),
        template_files=TEMPLATE_FILES,
        form_titles=FORM_TITLES,
        export_readiness=_export_readiness(case),
        step_count=len(STEP_ORDER),
        csrf_token=session["csrf_token"],
        current_deadlines=current_deadlines,
        deadline_labels=deadline_labels,
        awareness=awareness,
        evidence_items=evidence_items,
        evidence_references=references_by_id,
        evidence_ids={str(item.get("evidence_id", "")) for item in case.get("evidence", [])},
        review_43_datetime=_datetime_local_value(
            case.get("evidence_meta", {}).get("review", {}).get("43_at", "")
        ),
        current_submission=submission_record,
        current_submission_state=submission_state(
            submission_record, case.get("evidence", [])
        ),
        srp_mapping=build_srp_fields(case, SCHEMA),
        enisa_glossary_updated=ENISA_GLOSSARY_UPDATED,
        enisa_glossary_checked=ENISA_GLOSSARY_CHECKED,
        enisa_glossary_url=ENISA_GLOSSARY_URL,
        srp_platform_version=SRP_PLATFORM_VERSION,
        srp_platform_updated=SRP_PLATFORM_UPDATED,
        d7_review_fields=D7_REVIEW_FIELDS,
        schema_missing=MISSING_TEMPLATES,
        stage_labels=STAGE_LABELS,
        now_local=_local_now(),
    )


@app.route("/")
def index():
    all_cases = STORE.list()
    for item in all_cases:
        if _migrate_case_workflow(item):
            STORE.save(item)
    cases = [case for case in all_cases if not case.get("trashed_at")]
    trashed_count = sum(1 for case in all_cases if case.get("trashed_at"))
    return render_template(
        "index.html",
        cases=cases,
        trashed_count=trashed_count,
        csrf_token=session["csrf_token"],
        schema_missing=MISSING_TEMPLATES,
        step_count=len(STEP_ORDER),
        step_titles=STEP_TITLES,
    )


@app.route("/trash")
def trash():
    trashed_cases = [case for case in STORE.list() if case.get("trashed_at")]
    return render_template(
        "trash.html",
        cases=trashed_cases,
        csrf_token=session["csrf_token"],
    )


@app.post("/cases")
def create_case():
    _check_csrf()
    try:
        case = _new_case()
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("index"))
    STORE.save(case)
    return redirect(url_for("case_page", case_id=case["id"], step="7.1"))


@app.post("/cases/<case_id>/trash")
def trash_case(case_id: str):
    _check_csrf()
    case = _case_or_404(case_id)
    case["trashed_at"] = _local_now()
    _record_event(case, "案件已移至垃圾桶")
    STORE.save(case)
    flash(f"案件 {case.get('case_number', '')} 已移至垃圾桶。", "success")
    return redirect(url_for("index"))


@app.post("/trash/<case_id>/delete")
def delete_trashed_case(case_id: str):
    _check_csrf()
    case = STORE.get(case_id)
    if case is None or not case.get("trashed_at"):
        abort(404)
    case_number = case.get("case_number", "")
    if not STORE.delete(case_id):
        abort(404)
    flash(f"案件 {case_number} 已永久刪除。", "success")
    return redirect(url_for("trash"))


@app.post("/trash/empty")
def empty_trash():
    _check_csrf()
    trashed_ids = [
        case["id"] for case in STORE.list()
        if case.get("trashed_at") and case.get("id")
    ]
    deleted_count = STORE.delete_many(trashed_ids)
    if deleted_count:
        flash(f"垃圾桶已清空，永久刪除 {deleted_count} 件案件。", "success")
    else:
        flash("垃圾桶目前是空的。", "success")
    return redirect(url_for("trash"))


@app.get("/cases/<case_id>")
def case_page(case_id: str):
    case = _case_or_404(case_id)
    step = request.args.get("step", case.get("current_step", "7.1"))
    step = LEGACY_STEP_MAP.get(step, step)
    if step not in STEP_ORDER:
        step = case.get("current_step", "7.1")
    _set_report_stage(case, step)
    case["current_step"] = step
    STORE.save(case)
    return _render_case(case, step)


@app.post("/cases/<case_id>/step/<step>")
def save_step(case_id: str, step: str):
    _check_csrf()
    if step not in STEP_ORDER:
        abort(404)
    case = _case_or_404(case_id)
    values = request.form.to_dict(flat=True)
    if request.form.getlist("intermediate_requested"):
        values["intermediate_requested"] = request.form.getlist("intermediate_requested")[-1]
    intent = values.get("intent", "save")
    try:
        _apply_step(case, step, values, intent)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("case_page", case_id=case_id, step=step))
    STORE.save(case)
    if intent == "save":
        flash("已保存。", "success")
    return redirect(url_for("case_page", case_id=case_id, step=case["current_step"]))


@app.post("/api/cases/<case_id>/auto-save")
def auto_save(case_id: str):
    _check_csrf()
    case = _case_or_404(case_id)
    body = request.get_json(silent=True) or {}
    step = body.get("step", "")
    values = body.get("values", {})
    if step not in STEP_ORDER or not isinstance(values, dict):
        return jsonify({"ok": False, "error": "無效的步驟或欄位資料。"}), 400
    try:
        _apply_step(case, step, values, "save")
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    STORE.save(case)
    result = {
        "ok": True,
        "saved_at": case["updated_local"],
        "export_readiness": _export_readiness(case),
    }
    if step in {"7.5", "7.6", "7.9"} or (
        step == "7.8" and case.get("srp", {}).get("intermediate_requested")
    ):
        result["submission_state"] = submission_state(
            _submission_for_step(case, step), case.get("evidence", [])
        )
    return jsonify(result)


@app.post("/api/cases/<case_id>/evidence")
def create_evidence(case_id: str):
    _check_csrf()
    case = _case_or_404(case_id)
    body = request.get_json(silent=True) or {}
    evidence_id = str(body.get("evidence_id", "")).strip()
    if not evidence_id:
        return jsonify({"ok": False, "error": "請填寫 Evidence ID。"}), 400
    source_step = str(body.get("step", ""))
    field_name = str(body.get("field_name", ""))
    match = re.fullmatch(r"field__(D[1-6])__(\d+)__evidence_id", field_name)
    valid_rows = {
        (code, row)
        for code, rows in WORKFLOW_FIELDS.get(source_step, ())
        for row in rows
    }
    if (
        source_step not in STEP_ORDER
        or not match
        or (match.group(1), int(match.group(2))) not in valid_rows
    ):
        return jsonify({"ok": False, "error": "無法確認目前要填入 Evidence ID 的欄位，請重新載入頁面。"}), 400
    if any(item.get("evidence_id") == evidence_id for item in case.get("evidence", [])):
        return jsonify({"ok": False, "error": "此 Evidence ID 已存在，請使用唯一編號。"}), 409

    record = {
        "evidence_id": evidence_id,
        "obtained_at": str(body.get("obtained_at", "")).strip(),
        "timezone": str(body.get("timezone", "")).strip(),
        "kind": str(body.get("kind", "")).strip(),
        "description": str(body.get("description", "")).strip(),
        "source": str(body.get("source", "")).strip(),
        "location": str(body.get("location", "")).strip(),
        "custodian": str(body.get("custodian", "")).strip(),
    }
    if record["obtained_at"]:
        try:
            datetime.fromisoformat(record["obtained_at"])
        except ValueError:
            return jsonify({"ok": False, "error": "取得時間格式無效，請使用日期時間選擇器。"}), 400
    if record["timezone"]:
        try:
            ZoneInfo(record["timezone"])
        except ZoneInfoNotFoundError:
            return jsonify({"ok": False, "error": "時區請使用有效的 IANA 名稱，例如 Asia/Taipei。"}), 400

    case.setdefault("evidence", []).append(record)
    _apply_template_fields(case, match.group(1), {field_name: evidence_id},
                           (int(match.group(2)),))
    _record_event(case, f"已建立 Evidence ID {evidence_id} 並選用於 {source_step}")
    STORE.save(case)
    return jsonify({
        "ok": True,
        "evidence": record,
        "saved_at": case["updated_local"],
        "export_readiness": _export_readiness(case),
    })


@app.post("/api/cases/<case_id>/awareness")
def save_awareness(case_id: str):
    _check_csrf()
    case = _case_or_404(case_id)
    body = request.get_json(silent=True) or {}
    error = _apply_awareness(case, body)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    _record_event(case, "Awareness Time 已更新")
    STORE.save(case)
    return jsonify({
        "ok": True,
        "deadlines": {
            "24": deadline_iso(case, 24),
            "72": deadline_iso(case, 72),
        },
        "deadline_labels": {
            "24": deadline_display(case, 24),
            "72": deadline_display(case, 72),
        },
        "awareness": case["awareness"],
        "saved_at": case["updated_local"],
        "export_readiness": _export_readiness(case),
    })


@app.get("/cases/<case_id>/report.pdf")
def report_pdf(case_id: str):
    case = _case_or_404(case_id)
    try:
        data = build_srp_pdf(case, SCHEMA)
    except RuntimeError as exc:
        abort(503, description=str(exc))
    filename = f"{_safe_filename(case.get('case_number', 'case'))}_SRP_Report.pdf"
    return send_file(
        io.BytesIO(data), mimetype="application/pdf", as_attachment=True,
        download_name=filename,
    )


@app.get("/cases/<case_id>/export/<code>.xlsx")
def export_xlsx(case_id: str, code: str):
    case = _case_or_404(case_id)
    if code not in (*TEMPLATE_FILES.keys(), "D7"):
        abort(404)
    try:
        data = build_xlsx(code, TEMPLATE_DIR, case, SCHEMA)
    except FileNotFoundError as exc:
        abort(503, description=str(exc))
    filename = f"{_safe_filename(case.get('case_number', 'case'))}_{code}.xlsx"
    return send_file(
        io.BytesIO(data),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )


@app.get("/cases/<case_id>/export/all.zip")
def export_bundle(case_id: str):
    case = _case_or_404(case_id)
    bundle = io.BytesIO()
    prefix = _safe_filename(case.get("case_number", "case"))
    try:
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
            for code in ("D1", "D2", "D3", "D4", "D5", "D6", "D7"):
                data = build_xlsx(code, TEMPLATE_DIR, case, SCHEMA)
                archive.writestr(f"{prefix}/{prefix}_{code}.xlsx", data)
            archive.writestr(
                f"{prefix}/{prefix}_SRP_Report.pdf",
                build_srp_pdf(case, SCHEMA),
            )
            archive.writestr(
                f"{prefix}/README.txt",
                "PSIRT CRA 本機匯出包\n"
                "SRP Report PDF 為內部人工填寫參考，不代表已輸入或提交至 SRP。\n"
                "D1-D7 為來源範本副本；請依公司核准流程覆核。\n",
            )
    except (FileNotFoundError, RuntimeError) as exc:
        abort(503, description=str(exc))
    bundle.seek(0)
    return send_file(
        bundle, mimetype="application/zip", as_attachment=True,
        download_name=f"{prefix}_CRA_Export.zip",
    )


@app.get("/health")
def health():
    return jsonify({"status": "ok", "bind": "127.0.0.1"})


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return safe or "PSIRT-CRA-Case"


@app.errorhandler(400)
def bad_request(error):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": getattr(error, "description", "請求無效。")}), 400
    return make_response(
        render_template("error.html", code=400, message=getattr(error, "description", "請求無效。")),
        400,
    )


@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "找不到指定案件。"}), 404
    return make_response(render_template("error.html", code=404, message="找不到指定案件。"), 404)


@app.errorhandler(503)
def service_unavailable(error):
    return make_response(
        render_template(
            "error.html", code=503,
            message=getattr(error, "description", "目前無法產生匯出檔。"),
        ),
        503,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PSIRT_PORT", "8765"))
    print(f"PSIRT CRA 本機輔助平台： http://127.0.0.1:{port}")
    print(f"加密資料庫位置：{DATABASE_PATH}")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)

