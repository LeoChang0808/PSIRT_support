"""Generate an internal, draft SRP hand-entry report."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from srp_fields import (
    ENISA_GLOSSARY_CHECKED,
    ENISA_GLOSSARY_UPDATED,
    ENISA_GLOSSARY_VERSION,
    ENISA_GLOSSARY_URL,
    SRP_PLATFORM_UPDATED,
    SRP_PLATFORM_VERSION,
    build_srp_fields,
)
from submission import current_submission, format_report_time, submission_state
from forms import evidence_references

STAGE_LABELS = {
    "EW": "Early Warning（24 小時）",
    "72h": "72-hour Notification（72 小時）",
    "Intermediate": "Intermediate Report（依 CSIRT 要求）",
    "Final": "Final Report",
}


def _register_chinese_font() -> str:
    font_name = "PSIRT-Local-CJK"
    if font_name in pdfmetrics.getRegisteredFontNames():
        return font_name
    candidates = (
        ("/System/Library/Fonts/AppleSDGothicNeo.ttc", 0),
        ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
        ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
    )
    for path, index in candidates:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont(font_name, path, subfontIndex=index))
                return font_name
            except Exception:
                continue
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        return "STSong-Light"
    except Exception as exc:
        raise RuntimeError("找不到可用的中文 PDF 字型，無法產生 SRP Report PDF。") from exc


def _p(text: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)


def build_srp_pdf(case: dict, schema: dict[str, list[dict]]) -> bytes:
    font = _register_chinese_font()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"PSIRT SRP Report {case.get('case_number', '')}",
        author="PSIRT CRA Local Reporting Assistant",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "PSIRTTitle", parent=styles["Title"], fontName=font, fontSize=18,
        leading=24, textColor=colors.HexColor("#18324b"), alignment=TA_LEFT,
        spaceAfter=5 * mm,
    )
    heading = ParagraphStyle(
        "PSIRTHeading", parent=styles["Heading2"], fontName=font, fontSize=12,
        leading=16, textColor=colors.HexColor("#166534"), spaceBefore=5 * mm,
        spaceAfter=2 * mm,
    )
    body = ParagraphStyle(
        "PSIRTBody", parent=styles["BodyText"], fontName=font, fontSize=9,
        leading=13, wordWrap="CJK", spaceAfter=1.5 * mm,
    )
    cell = ParagraphStyle("PSIRTCell", parent=body, fontSize=8, leading=11)

    srp = case.get("srp", {})
    stage = srp.get("stage", "EW")
    report_type = srp.get("type", "AEV")
    srp_mapping = build_srp_fields(case, schema)
    generated = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    submission = current_submission(case)
    submission_status = submission_state(submission, case.get("evidence", []))
    entry_completed = format_report_time(
        submission.get("entry_completed_at", ""),
        submission.get("entry_timezone", "Asia/Taipei"),
    )
    actual_submission = (
        format_report_time(
            submission.get("submitted_at", ""),
            submission.get("submitted_timezone", "Asia/Taipei"),
        )
        if submission_status["confirmed"] else "未確認正式提交"
    )
    story = [
        _p("SRP 手動填寫資料報告", title),
        _p(
            "草稿／內部工作文件：欄位清單依 ENISA SRP Glossary "
            f"{ENISA_GLOSSARY_VERSION}（更新 {ENISA_GLOSSARY_UPDATED}；本機核對 "
            f"{ENISA_GLOSSARY_CHECKED}）整理，仍須由 SRP AR 對照目前 SRP 畫面覆核。"
            "本報告未連線、未輸入、未儲存，也未提交至 ENISA SRP。",
            body,
        ),
        Spacer(1, 2 * mm),
    ]
    metadata = [
        [_p("案件編號", cell), _p(case.get("case_number", ""), cell),
         _p("產品／案件", cell), _p(case.get("title", ""), cell)],
        [_p("通報類型", cell), _p(report_type, cell),
         _p("SRP 階段", cell), _p(STAGE_LABELS.get(stage, stage), cell)],
        [_p("產生時間", cell), _p(generated, cell),
         _p("知悉時間", cell), _p(case.get("awareness", {}).get("local", "待填"), cell)],
        [_p("知悉時區", cell), _p(case.get("awareness", {}).get("timezone", "待填"), cell),
         _p("SRP 版本參照", cell), _p(
             f"平台 {SRP_PLATFORM_VERSION}（{SRP_PLATFORM_UPDATED}）；"
             f"Glossary {ENISA_GLOSSARY_VERSION}", cell)],
        [_p("SRP 欄位輸入完成時間", cell), _p(entry_completed or "待回報", cell),
         _p("平台正式提交時間", cell), _p(actual_submission, cell)],
        [_p("目前 SRP 狀態", cell), _p(submission_status["label"], cell),
         _p("參考號／回執 Evidence ID", cell),
         _p("／".join(value for value in (
             submission.get("reference_number", ""),
             submission.get("receipt_evidence_id", ""),
         ) if value), cell)],
    ]
    meta_table = Table(metadata, colWidths=[25 * mm, 57 * mm, 25 * mm, 70 * mm])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f1f5f9")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([meta_table, Spacer(1, 4 * mm)])
    story.append(_p("填寫提醒", heading))
    story.append(_p(
        "本工具不判定 AEV／重大事件、不核准 Awareness Time，也不會替人員送出 SRP。"
        "請 AR 依核准程序與 ENISA 當前欄位逐項確認；缺漏或未知值不得推測。",
        body,
    ))
    story.append(_p(
        f"欄位基準：ENISA SRP Glossary {ENISA_GLOSSARY_VERSION}；"
        f"[官方 Glossary] {ENISA_GLOSSARY_URL}", body,
    ))
    story.append(_p("本階段 SRP 欄位對照", heading))
    if stage == "Intermediate":
        story.append(_p(
            "Intermediate Report 的欄位依 CSIRT 個別要求決定。請依 CSIRT 要求及目前 SRP 畫面逐欄填寫；"
            "本報告不推定或產生通用欄位清單。",
            body,
        ))
    else:
        story.append(_p(
            f"依案件所選類型與階段列出 {len(srp_mapping['fields'])} 個適用欄位；"
            f"尚缺 {srp_mapping['required_missing']} 個 Required／Mandatory 欄位。"
            "此缺漏數不包含條件式要求，請由 AR 確認適用性。",
            body,
        ))
        field_rows = [[
            _p("SRP 欄位", cell), _p("階段要求", cell),
            _p("目前資料／值", cell), _p("來源／Evidence ID", cell),
        ]]
        for field in srp_mapping["fields"]:
            source_text = "／".join(
                value for value in (field["source"], field["evidence_id"]) if value
            )
            field_rows.append([
                _p(f"{field['number']} · {field['name']}", cell),
                _p(field["requirement"], cell),
                _p(field["value"] or ("待補" if field["missing"] else "待確認"), cell),
                _p(source_text, cell),
            ])
        field_table = Table(
            field_rows, colWidths=[59 * mm, 31 * mm, 50 * mm, 37 * mm], repeatRows=1,
        )
        field_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(field_table)

    evidence = case.get("evidence", [])
    if evidence:
        references_by_id = evidence_references(case, schema)
        story.append(_p("D7 證據索引", heading))
        evidence_rows = [[_p(name, cell) for name in
                          ("Evidence ID", "取得時間／時區", "類型／描述", "來源／位置", "保管人／引用欄位")]]
        for item in evidence:
            obtained_at = " ".join(value for value in (
                item.get("obtained_at", ""), item.get("timezone", "")
            ) if value)
            evidence_rows.append([
                _p(item.get("evidence_id", ""), cell),
                _p(obtained_at, cell),
                _p("／".join(x for x in (item.get("kind", ""), item.get("description", "")) if x), cell),
                _p("／".join(x for x in (item.get("source", ""), item.get("location", "")) if x), cell),
                _p("／".join(x for x in (
                    item.get("custodian", ""),
                    "；".join(references_by_id.get(str(item.get("evidence_id", "")), [])),
                ) if x), cell),
            ])
        evidence_table = Table(evidence_rows, colWidths=[24 * mm, 27 * mm, 43 * mm, 43 * mm, 35 * mm], repeatRows=1)
        evidence_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(evidence_table)

    review_labels = {
        "35": "原始檔案完整性／校驗方式（適用時）",
        "36": "存取／保管權限",
        "37": "相關 D1～D6 的 Case ID 一致性",
        "38": "證據編號重複／遺漏檢查結果",
        "39": "證據版本及更動紀錄",
        "40": "主管機關通報提交證據核對",
        "41": "使用者通知／發布證據核對",
        "42": "法規通報結案／內部歸檔狀態",
        "43": "保管單位／複核人／複核時間",
    }
    review = case.get("evidence_meta", {}).get("review", {})
    review_rows = [[_p("D7 品質／結案核對", cell), _p("記錄", cell)]]
    for row, label in review_labels.items():
        value = review.get(row, "")
        if row == "43":
            details = review.get("43_details", value)
            review_time = " ".join(item for item in (
                review.get("43_at", ""), review.get("43_timezone", "")
            ) if item)
            value = "；".join(item for item in (details, review_time) if item)
        if value:
            review_rows.append([_p(label, cell), _p(value, cell)])
    if len(review_rows) > 1:
        story.append(_p("D7 證據品質與結案核對", heading))
        review_table = Table(review_rows, colWidths=[70 * mm, 107 * mm], repeatRows=1)
        review_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(review_table)

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(font, 7)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(16 * mm, 10 * mm, "PSIRT 內部填寫參考 · 尚未提交至 SRP")
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"第 {document.page} 頁")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
