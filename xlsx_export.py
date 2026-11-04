"""Populate copies of the supplied D1-D7 workbooks without changing originals."""
from __future__ import annotations

import copy
import posixpath
import re
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree as ET

from forms import (
    D7_TEMPLATE_FILE, NS, TEMPLATE_FILES, _form_sheet_path, _shared_strings,
    evidence_references, value_for,
)
from time_utils import awareness_datetime, deadline_display
from submission import all_submissions, format_report_time, submission_state

ET.register_namespace("", NS["m"])
ET.register_namespace("r", NS["r"])


def _cell_column(ref: str) -> str:
    return re.sub(r"\d+", "", ref)


def _cell_row(ref: str) -> int:
    return int(re.sub(r"\D+", "", ref))


def _column_number(col: str) -> int:
    result = 0
    for char in col:
        result = result * 26 + ord(char.upper()) - 64
    return result


def _get_row(sheet_data: ET.Element, row_number: int) -> ET.Element:
    for row in sheet_data.findall("m:row", NS):
        if int(row.attrib["r"]) == row_number:
            return row
    row = ET.Element("{" + NS["m"] + "}row", {"r": str(row_number)})
    following = next(
        (item for item in sheet_data.findall("m:row", NS)
         if int(item.attrib["r"]) > row_number),
        None,
    )
    if following is None:
        sheet_data.append(row)
    else:
        sheet_data.insert(list(sheet_data).index(following), row)
    return row


def _get_cell(row: ET.Element, column: str, row_number: int) -> ET.Element:
    ref = f"{column}{row_number}"
    for cell in row.findall("m:c", NS):
        if cell.attrib.get("r") == ref:
            return cell
    cell = ET.Element("{" + NS["m"] + "}c", {"r": ref})
    existing = row.findall("m:c", NS)
    before = next(
        (item for item in existing
         if _column_number(_cell_column(item.attrib["r"])) > _column_number(column)),
        None,
    )
    if before is None:
        row.append(cell)
    else:
        row.insert(list(row).index(before), cell)
    return cell


def _set_text(sheet_data: ET.Element, cell_ref: str, text: object) -> None:
    row_number = _cell_row(cell_ref)
    column = _cell_column(cell_ref)
    row = _get_row(sheet_data, row_number)
    cell = _get_cell(row, column, row_number)
    for child in list(cell):
        cell.remove(child)
    value = "" if text is None else str(text)
    cell.attrib["t"] = "inlineStr"
    inline = ET.SubElement(cell, "{" + NS["m"] + "}is")
    node = ET.SubElement(inline, "{" + NS["m"] + "}t")
    if value[:1].isspace() or value[-1:].isspace():
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    node.text = value


def _set_style(sheet_data: ET.Element, cell_ref: str, style: str) -> None:
    row_number = _cell_row(cell_ref)
    column = _cell_column(cell_ref)
    row = _get_row(sheet_data, row_number)
    cell = _get_cell(row, column, row_number)
    cell.set("s", style)


def _shift_rows(sheet: ET.Element, threshold: int, amount: int) -> None:
    """Insert blank data rows before the D7 quality-review section."""
    if amount <= 0:
        return
    for row in sheet.findall(".//m:sheetData/m:row", NS):
        old = int(row.attrib["r"])
        if old >= threshold:
            new = old + amount
            row.attrib["r"] = str(new)
            for cell in row.findall("m:c", NS):
                cell.attrib["r"] = re.sub(r"\d+$", str(new), cell.attrib["r"])
    for element in sheet.iter():
        for attribute in ("ref", "sqref"):
            value = element.attrib.get(attribute)
            if value:
                def shift_ref(match):
                    col, row = match.group(1), int(match.group(2))
                    return f"{col}{row + amount if row >= threshold else row}"
                element.attrib[attribute] = re.sub(
                    r"([A-Z]{1,3})(\d+)", shift_ref, value
                )
        formula = element.text if element.tag.endswith("}f") else None
        if formula:
            def shift_formula(match):
                col, row = match.group(1), int(match.group(2))
                return f"{col}{row + amount if row >= threshold else row}"
            element.text = re.sub(r"\b([A-Z]{1,3})(\d+)\b", shift_formula, formula)

    sheet_data = sheet.find(".//m:sheetData", NS)
    if sheet_data is not None:
        template_row = next(
            (row for row in sheet_data.findall("m:row", NS)
             if int(row.attrib["r"]) == threshold - 1),
            None,
        )
        if template_row is not None:
            for offset in range(amount):
                number = threshold + offset
                new_row = copy.deepcopy(template_row)
                new_row.attrib["r"] = str(number)
                for cell in new_row.findall("m:c", NS):
                    cell.attrib["r"] = re.sub(r"\d+$", str(number), cell.attrib["r"])
                    for child in list(cell):
                        cell.remove(child)
                    cell.attrib.pop("t", None)
                following = next(
                    (row for row in sheet_data.findall("m:row", NS)
                     if int(row.attrib["r"]) > number),
                    None,
                )
                if following is None:
                    sheet_data.append(new_row)
                else:
                    sheet_data.insert(list(sheet_data).index(following), new_row)


def _replace_sheet(template_path: Path, sheet_path: str, sheet: ET.Element) -> bytes:
    output = BytesIO()
    replacement = ET.tostring(sheet, encoding="utf-8", xml_declaration=True)
    with ZipFile(template_path, "r") as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = replacement if item.filename == sheet_path else source.read(item.filename)
            target.writestr(item, data)
    return output.getvalue()


def build_xlsx(
    code: str,
    template_directory: Path,
    case: dict,
    schema: dict[str, list[dict]],
) -> bytes:
    filename = D7_TEMPLATE_FILE if code == "D7" else TEMPLATE_FILES.get(code)
    if not filename:
        raise ValueError(f"未知表單代碼：{code}")
    template_path = Path(template_directory) / filename
    if not template_path.exists():
        raise FileNotFoundError(f"找不到 {code} 原始範本：{filename}")

    with ZipFile(template_path) as archive:
        path = _form_sheet_path(archive)
        shared = _shared_strings(archive)
        sheet = ET.fromstring(archive.read(path))
        sheet_data = sheet.find(".//m:sheetData", NS)
        if sheet_data is None:
            raise ValueError(f"{code} 範本工作表缺少資料區。")

        if code != "D7":
            _set_text(sheet_data, "C6", case.get("case_number", ""))
            _set_text(sheet_data, "C7", case.get("updated_local", ""))
            for field in schema.get(code, []):
                row = field["row"]
                values = case.get("forms", {}).get(code, {}).get(str(row), {})
                entry = value_for(case, code, field, "entry")
                if entry:
                    _set_text(sheet_data, f"C{row}", entry)
                if values.get("note"):
                    _set_text(sheet_data, f"D{row}", values["note"])
                if values.get("evidence_id"):
                    _set_text(sheet_data, f"E{row}", values["evidence_id"])
            if code == "D4":
                awareness = awareness_datetime(case)
                awareness_text = (
                    awareness.strftime("%Y-%m-%d %H:%M %Z") if awareness else ""
                )
                for field in schema.get("D4", []):
                    label = field["label"].casefold()
                    if "awareness time" in label:
                        _set_text(sheet_data, f"C{field['row']}", awareness_text)
                    elif "24h" in label:
                        _set_text(sheet_data, f"C{field['row']}", deadline_display(case, 24))
                    elif "72h" in label:
                        _set_text(sheet_data, f"C{field['row']}", deadline_display(case, 72))
            if code == "D5":
                records = all_submissions(case)
                stage_rows = {"EW": 47, "72h": 48, "Intermediate": 49, "Final": 50}
                combined: dict[str, list[dict]] = {}
                for key, record in records:
                    report_type, _, stage = key.partition("_")
                    if stage in stage_rows:
                        combined.setdefault(stage, []).append({
                            "type": report_type,
                            "record": record,
                            "state": submission_state(record, case.get("evidence", [])),
                        })
                for stage, row in stage_rows.items():
                    entries = combined.get(stage, [])
                    if not entries:
                        continue
                    actual_times = []
                    references = []
                    statuses = []
                    receipts = []
                    notes = []
                    for item in entries:
                        record, state = item["record"], item["state"]
                        prefix = item["type"] + " · "
                        if state["confirmed"]:
                            actual_times.append(prefix + format_report_time(
                                record.get("submitted_at", ""),
                                record.get("submitted_timezone", "Asia/Taipei"),
                            ))
                        if record.get("reference_number"):
                            references.append(prefix + record["reference_number"])
                        statuses.append(prefix + state["label"])
                        if record.get("receipt_evidence_id"):
                            receipts.append(prefix + record["receipt_evidence_id"])
                        if record.get("entry_completed_at"):
                            notes.append(prefix + "欄位完成 " + format_report_time(
                                record["entry_completed_at"],
                                record.get("entry_timezone", "Asia/Taipei"),
                            ))
                    _set_text(sheet_data, f"B{row}", "\n".join(actual_times))
                    _set_text(sheet_data, f"C{row}", "\n".join(references))
                    _set_text(sheet_data, f"D{row}", "\n".join(statuses))
                    _set_text(sheet_data, f"E{row}", "\n".join(receipts))
                    _set_text(sheet_data, f"F{row}", "\n".join(notes))

                _set_text(sheet_data, "A61", "SRP 人工輸入／提交時間")
                _set_style(sheet_data, "A61", "17")
                headers = (
                    "類型", "階段", "欄位輸入完成時間", "平台正式提交時間",
                    "狀態", "SRP 參考號／回執 Evidence ID",
                )
                for column, header in zip("ABCDEF", headers):
                    cell_ref = f"{column}62"
                    _set_style(sheet_data, cell_ref, "10")
                    _set_text(sheet_data, cell_ref, header)
                for offset, (key, record) in enumerate(records, start=63):
                    report_type, _, stage = key.partition("_")
                    state = submission_state(record, case.get("evidence", []))
                    row_values = (
                        report_type,
                        stage,
                        format_report_time(
                            record.get("entry_completed_at", ""),
                            record.get("entry_timezone", "Asia/Taipei"),
                        ),
                        format_report_time(
                            record.get("submitted_at", ""),
                            record.get("submitted_timezone", "Asia/Taipei"),
                        ) if state["confirmed"] else "",
                        state["label"],
                        "／".join(value for value in (
                            record.get("reference_number", ""),
                            record.get("receipt_evidence_id", ""),
                        ) if value),
                    )
                    for column, value in zip("ABCDEF", row_values):
                        cell_ref = f"{column}{offset}"
                        _set_style(sheet_data, cell_ref, "11")
                        _set_text(sheet_data, cell_ref, value)
        else:
            evidence_meta = case.get("evidence_meta", {})
            evidence_rows = case.get("evidence", [])
            references_by_id = evidence_references(case, schema)
            _set_text(sheet_data, "D6", case.get("case_number", ""))
            _set_text(sheet_data, "D7", case.get("title", ""))
            _set_text(sheet_data, "D8", evidence_meta.get("custodian", ""))
            _set_text(sheet_data, "D9", evidence_meta.get("location", ""))
            _set_text(sheet_data, "D10", case.get("updated_local", ""))
            review = evidence_meta.get("review", {})
            for row in range(35, 44):
                value = review.get(str(row), "")
                if row == 43:
                    details = review.get("43_details", value)
                    review_time = review.get("43_at", "")
                    review_timezone = review.get("43_timezone", "")
                    timestamp = " ".join(
                        item for item in (review_time, review_timezone) if item
                    )
                    value = "；".join(item for item in (details, timestamp) if item)
                if value:
                    _set_text(sheet_data, f"D{row}", value)
            capacity = 21
            if len(evidence_rows) > capacity:
                _shift_rows(sheet, 34, len(evidence_rows) - capacity)
                sheet_data = sheet.find(".//m:sheetData", NS)
            _set_text(sheet_data, "H12", "引用欄位")
            for index, evidence in enumerate(evidence_rows):
                row = 13 + index
                for column, key in zip(
                    "ABCDEFGH",
                    ("evidence_id", "obtained_at", "kind", "description",
                     "source", "location", "custodian", "references"),
                ):
                    value = "；".join(
                        references_by_id.get(str(evidence.get("evidence_id", "")), [])
                    ) if key == "references" else evidence.get(key, "")
                    if key == "obtained_at" and evidence.get("timezone"):
                        timezone_name = str(evidence.get("timezone", "")).strip()
                        if timezone_name and not str(value).endswith(timezone_name):
                            value = f"{value} {timezone_name}".strip()
                    _set_text(sheet_data, f"{column}{row}", value)
    return _replace_sheet(template_path, path, sheet)

