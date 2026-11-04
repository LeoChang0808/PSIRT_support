"""Read field labels from the existing, read-only D1-D6 XLSX templates."""
from __future__ import annotations

import posixpath
import re
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

TEMPLATE_FILES = {
    "D1": "D1_產品與 CRA 適用性清冊 (Product Applicability Register).xlsx",
    "D2": "D2_漏洞與資安事件接收登錄表 (Case Intake Log).xlsx",
    "D3": "D3_產品資安影響與通報條件評估表 (Impact  Severity Assessment).xlsx",
    "D4": "D4_法規通報決策與期限追蹤表 (Reporting Decision Record & SLA Tracker).xlsx",
    "D5": "D5_SRP法規通報提交紀錄表 (SRP Submission Record).xlsx",
    "D6": "D6_受影響使用者通知與資安公告表 (Customer Notification  Security Advisory).xlsx",
}
D7_TEMPLATE_FILE = "D7_案件檔案與客觀證據清冊 (Case File & Evidence Register).xlsx"


def _column(cell_ref: str) -> str:
    return re.sub(r"\d+", "", cell_ref)


def _shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.findall(".//m:t", NS))
        for item in root.findall("m:si", NS)
    ]


def cell_text(cell: ET.Element | None, shared: list[str]) -> str:
    if cell is None:
        return ""
    kind = cell.attrib.get("t")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//m:t", NS))
    value = cell.find("m:v", NS)
    if value is None or value.text is None:
        return ""
    if kind == "s":
        try:
            return shared[int(value.text)]
        except (IndexError, ValueError):
            return ""
    return value.text


def _form_sheet_path(archive: ZipFile) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in relationships}
    for sheet in workbook.findall("m:sheets/m:sheet", NS):
        if sheet.attrib.get("name") != "表單":
            continue
        target = relmap[sheet.attrib["{" + NS["r"] + "}id"]]
        if target.startswith("/"):
            return target.lstrip("/")
        if target.startswith("xl/"):
            return target
        return posixpath.normpath(posixpath.join("xl", target))
    raise ValueError("範本內找不到「表單」工作表。")


def load_form_schema(template_directory: Path) -> tuple[dict[str, list[dict]], list[str]]:
    """Return row-addressed fields and a list of missing templates."""
    schemas: dict[str, list[dict]] = {}
    missing: list[str] = []
    for code, filename in TEMPLATE_FILES.items():
        path = Path(template_directory) / filename
        if not path.exists():
            schemas[code] = []
            missing.append(filename)
            continue
        try:
            with ZipFile(path) as archive:
                shared = _shared_strings(archive)
                sheet = ET.fromstring(archive.read(_form_sheet_path(archive)))
        except Exception as exc:
            schemas[code] = []
            missing.append(filename + "（無法讀取）")
            continue

        fields: list[dict] = []
        for row in sheet.findall(".//m:sheetData/m:row", NS):
            cells = {_column(cell.attrib.get("r", "")): cell for cell in row.findall("m:c", NS)}
            ordinal = cell_text(cells.get("A"), shared).strip()
            label = cell_text(cells.get("B"), shared).strip()
            if not ordinal.isdigit() or not label or label.startswith("欄位名稱"):
                continue
            fields.append({"row": int(row.attrib["r"]), "number": ordinal, "label": label})
        schemas[code] = fields
    return schemas, missing


def shared_field_key(label: str) -> str:
    """Create a conservative key for repeated, identically named fields."""
    normalized = re.sub(r"[\s_/／（）()、·:：-]+", "", label).casefold()
    if normalized.startswith("caseid") or normalized.startswith("案件編號"):
        return "case_id"
    if normalized in {"製造商名稱", "製造商"}:
        return "manufacturer_name"
    if normalized in {"產品名稱", "產品名稱型號"}:
        return "product_name"
    if normalized in {
        "疑似產品版本",
        "補充影響產品版本",
        "產品與版本",
        "受影響軟韌體版本",
    }:
        return "affected_product_version"
    return normalized


def value_for(case: dict, section: str, field: dict, value_name: str = "entry") -> str:
    row_key = str(field["row"])
    local = case.get("forms", {}).get(section, {}).get(row_key, {})
    if local.get(value_name):
        value = str(local[value_name])
        timezone_name = str(local.get("timezone", "")).strip()
        if value_name == "entry" and timezone_name and not value.endswith(timezone_name):
            return f"{value} {timezone_name}"
        return value
    if value_name == "entry":
        shared = case.get("shared_fields", {}).get(shared_field_key(field["label"]))
        if isinstance(shared, dict):
            shared = shared.get("value", "")
        if shared:
            return str(shared)
        if shared_field_key(field["label"]) == "case_id":
            return str(case.get("case_number", ""))
    return ""

