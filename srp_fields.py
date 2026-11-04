"""Versioned ENISA SRP Glossary field applicability and source mapping."""
from __future__ import annotations

from datetime import timezone

from forms import shared_field_key
from time_utils import awareness_datetime

ENISA_GLOSSARY_VERSION = "1.6"
ENISA_GLOSSARY_UPDATED = "2026-10-21"
ENISA_GLOSSARY_CHECKED = "2026-11-04"
SRP_PLATFORM_VERSION = "1.2.1"
SRP_PLATFORM_UPDATED = "2026-10-20"
ENISA_GLOSSARY_URL = (
    "https://www.enisa.europa.eu/topics/product-security/"
    "single-reporting-platform-srp/cra-srp-glossary2"
)

_COMMON = "Both"
_FIELDS = [
    ("1", "Notification type (Actively Exploited Vulnerability/Severe Incident)", _COMMON,
     {"EW": "Required", "72h": "N/A", "Final": "N/A"}, ()),
    ("2", "Title", _COMMON,
     {"EW": "Required", "72h": "N/A", "Final": "N/A"}, (("D2", 14),)),
    ("3", "Summary", _COMMON,
     {"EW": "Required", "72h": "N/A", "Final": "N/A"}, (("D2", 18),)),
    ("4", "Manufacturer name", _COMMON,
     {"EW": "Required", "72h": "N/A", "Final": "N/A"}, (("D1", 13),)),
    ("5", "Member States where product available (CDaC and Concerned CSIRTs)", _COMMON,
     {"EW": "Required", "72h": "N/A", "Final": "N/A"}, (("D1", 23),)),
    ("6", "Product Name", _COMMON,
     {"EW": "Required", "72h": "N/A", "Final": "N/A"}, (("D1", 17),)),
    ("7", "Product Version", _COMMON,
     {"EW": "Required", "72h": "N/A", "Final": "N/A"}, (("D1", 19),)),
    ("7a", "Additional Information", _COMMON,
     {"EW": "Optional", "72h": "N/A", "Final": "N/A"}, (("D1", 20),)),
    ("8", "Product Type", _COMMON,
     {"EW": "Optional", "72h": "N/A", "Final": "N/A"}, ()),
    ("9", "Product class", _COMMON,
     {"EW": "Optional", "72h": "N/A", "Final": "N/A"}, ()),
    ("10", "Product category", _COMMON,
     {"EW": "Optional", "72h": "N/A", "Final": "N/A"}, ()),
    ("11", "End of the support indicator", _COMMON,
     {"EW": "Optional", "72h": "N/A", "Final": "N/A"}, ()),
    ("12", "Component name", _COMMON,
     {"EW": "Optional", "72h": "N/A", "Final": "N/A"}, ()),
    ("13", "Mitigating measure expected shortly", _COMMON,
     {"EW": "Optional", "72h": "N/A", "Final": "N/A"}, ()),
    ("14", "User Action able to reduce impact", _COMMON,
     {"EW": "Optional", "72h": "N/A", "Final": "N/A"}, (("D6", 20),)),
    ("15", "Considered sensitivity of information", _COMMON,
     {"EW": "Optional", "72h": "Optional", "Final": "N/A"}, ()),
    ("16", "Corrective or mitigating measures taken", _COMMON,
     {"EW": "Optional", "72h": "Optional", "Final": "Required"}, (("D3", 37),)),
    ("17", "Corrective or mitigating measures that users can take", _COMMON,
     {"EW": "Optional", "72h": "Optional", "Final": "Required"}, (("D6", 20),)),
    ("18", "Attack vector", _COMMON,
     {"EW": "N/A", "72h": "Optional", "Final": "N/A"}, ()),
    ("v19", "CVE ID", "AEV",
     {"EW": "Optional", "72h": "N/A", "Final": "N/A"}, ()),
    ("v20", "EUVD ID", "AEV",
     {"EW": "Optional", "72h": "N/A", "Final": "N/A"}, ()),
    ("v21", "General information", "AEV",
     {"EW": "Optional", "72h": "Required", "Final": "N/A"}, (("D2", 18), ("D3", 29))),
    ("v22", "Date when corrective or mitigating measure has been available", "AEV",
     {"EW": "Optional (after completion of v17)",
      "72h": "Optional (after completion of v17)", "Final": "Required"}, (("D6", 21),)),
    ("v23", "Details about the security update/corrective measure available", "AEV",
     {"EW": "Optional", "72h": "Optional", "Final": "Required"}, (("D3", 38),)),
    ("v24", "Description of the severity of the vulnerability", "AEV",
     {"EW": "Optional", "72h": "Optional", "Final": "Required"}, (("D3", 28),)),
    ("v25", "Description of the impact of the vulnerability", "AEV",
     {"EW": "Optional", "72h": "Optional", "Final": "Required"}, (("D3", 16),)),
    ("v26", "Date and time when you become aware of the Actively Exploited Vulnerability", "AEV",
     {"EW": "Mandatory", "72h": "N/A", "Final": "N/A"}, (), "awareness"),
    ("v26a", "Date and time when the Actively Exploited Vulnerability occurred (UTC time)", "AEV",
     {"EW": "Optional", "72h": "By default copied from previous step", "Final": "N/A"}, ()),
    ("v27", "Malicious actor that has exploited/is exploiting the vulnerability", "AEV",
     {"EW": "Optional", "72h": "Optional", "Final": "Required if such information available"},
     (("D3", 21),)),
    ("v28", "Particularly Exceptional Circumstances (PEC)", "AEV",
     {"EW": "N/A", "72h": "Optional", "Final": "N/A"}, ()),
    ("v29", "PEC Delay Reason", "AEV",
     {"EW": "N/A", "72h": "Optional upon PEC activation", "Final": "N/A"}, ()),
    ("v30", "Please provide further information", "AEV",
     {"EW": "N/A", "72h": "Optional under PEC activation", "Final": "N/A"}, ()),
    ("i31", "Incident is suspected of unlawful or malicious acts", "SI",
     {"EW": "Required", "72h": "By default copied from previous step, or updated",
      "Final": "N/A"}, ()),
    ("i32", "General information, about the nature of the incident", "SI",
     {"EW": "Optional", "72h": "Required", "Final": "N/A"}, (("D3", 16),)),
    ("i33", "Applied and ongoing mitigation measures", "SI",
     {"EW": "Optional", "72h": "Optional", "Final": "Required"}, (("D3", 37),)),
    ("i34", "Detailed description of the Severity of the incident", "SI",
     {"EW": "Optional", "72h": "Optional", "Final": "Required"}, (("D3", 28),)),
    ("i35", "Detailed description of the Impact of the incident", "SI",
     {"EW": "Optional", "72h": "Optional", "Final": "Required"}, (("D3", 16),)),
    ("i36", "Type of Threat or root cause that is likely to have triggered incident", "SI",
     {"EW": "Optional", "72h": "Optional", "Final": "Required"}, (("D3", 36),)),
    ("i37", "Date and time when you become aware of the incident (UTC time)", "SI",
     {"EW": "Mandatory", "72h": "N/A", "Final": "N/A"}, (), "awareness"),
    ("i38", "Date and time when the incident occurred (UTC time)", "SI",
     {"EW": "Optional", "72h": "Optional", "Final": "N/A"}, ()),
    ("i39", "Initial assessment of the incident", "SI",
     {"EW": "Optional", "72h": "Required", "Final": "N/A"}, (("D3", 28), ("D3", 30))),
    ("40", "AR Note", _COMMON,
     {"EW": "Optional", "72h": "Optional", "Final": "Optional"}, ()),
    ("41", "CSIRT Note", _COMMON,
     {"EW": "Optional", "72h": "Optional", "Final": "Optional"}, ()),
]


def _shared_value(case: dict, field_key: str) -> str:
    value = case.get("shared_fields", {}).get(field_key, "")
    if isinstance(value, dict):
        return str(value.get("value", ""))
    return str(value or "")


def _resolve_value(case: dict, schema: dict, candidates: tuple, special: str = "") -> tuple[str, str, str]:
    if special == "awareness":
        value = awareness_datetime(case)
        if value:
            utc_value = value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            return utc_value, "D4 · Awareness Time", ""
        return "", "D4 · Awareness Time", ""

    for code, row in candidates:
        field = next(
            (item for item in schema.get(code, []) if item["row"] == row),
            None,
        )
        if field is None:
            continue
        stored = case.get("forms", {}).get(code, {}).get(str(row), {})
        value = stored.get("entry", "") or _shared_value(
            case, shared_field_key(field["label"])
        )
        if value:
            return str(value), f"{code} · {field['label']}", str(stored.get("evidence_id", ""))
    if not candidates:
        return "", "無直接 D1–D7 欄位對照", ""
    first_code, first_row = candidates[0]
    field = next(
        (item for item in schema.get(first_code, []) if item["row"] == first_row),
        None,
    )
    source = f"{first_code} · {field['label']}" if field else f"{first_code} · 待核對來源"
    return "", source, ""


def build_srp_fields(case: dict, schema: dict) -> dict:
    srp = case.get("srp", {})
    report_type = srp.get("type", "AEV")
    stage = srp.get("stage", "EW")
    if stage == "Intermediate":
        return {
            "fields": [],
            "required_missing": 0,
            "mapping_status": "CSIRT request-specific",
            "version": ENISA_GLOSSARY_VERSION,
        }

    entries = []
    required_missing = 0
    for number, name, applies, stage_rules, candidates, *extra in _FIELDS:
        if applies not in {_COMMON, report_type}:
            continue
        requirement = stage_rules.get(stage, "N/A")
        if requirement == "N/A":
            continue
        special = extra[0] if extra else ""
        if number == "1":
            value = "Vulnerability (AEV)" if report_type == "AEV" else "Incident (SI)"
            source, evidence_id = "SRP 通報類型選擇", ""
        elif number == "2":
            mapped_value, source, evidence_id = _resolve_value(case, schema, candidates)
            value = case.get("title", "") if case.get("title") != "新案件" else mapped_value
        else:
            value, source, evidence_id = _resolve_value(case, schema, candidates, special)
        hard_required = requirement in {"Required", "Mandatory"}
        missing = hard_required and not value
        if missing:
            required_missing += 1
        entries.append({
            "number": number,
            "name": name,
            "applies": applies,
            "requirement": requirement,
            "value": value,
            "source": source,
            "evidence_id": evidence_id,
            "missing": missing,
            "status": "待補" if missing else ("已提供" if value else "待確認／選填"),
        })
    return {
        "fields": entries,
        "required_missing": required_missing,
        "mapping_status": "versioned",
        "version": ENISA_GLOSSARY_VERSION,
    }

