from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "deliverables" / "conclusion.pdf"
RESULTS = PROJECT_ROOT / "eval" / "results.json"

INK = colors.HexColor("#172329")
INK_SOFT = colors.HexColor("#536065")
PAPER = colors.HexColor("#F7F4EE")
SURFACE = colors.HexColor("#FFFDF8")
LINE = colors.HexColor("#D8D2C6")
ACCENT = colors.HexColor("#A33B32")
JADE = colors.HexColor("#2E665D")


def page_decor(canvas, doc):
    width, height = A4
    canvas.saveState()
    canvas.setFillColor(INK)
    canvas.rect(0, height - 42 * mm, width, 42 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("STSong-Light", 10)
    canvas.drawString(18 * mm, height - 13 * mm, "FINANCIAL REPORT RAG / WEEK 03")
    canvas.setFont("STSong-Light", 21)
    canvas.drawString(18 * mm, height - 25 * mm, "同一批财报，什么该建库？")
    canvas.setFont("STSong-Light", 9)
    canvas.setFillColor(colors.HexColor("#CAD4D1"))
    canvas.drawString(
        18 * mm,
        height - 33 * mm,
        "12 家 A 股白酒公司 · 2025 年年报 · 2,100 页 · 11 道真实评测",
    )
    canvas.setStrokeColor(LINE)
    canvas.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)
    canvas.setFillColor(INK_SOFT)
    canvas.setFont("STSong-Light", 8)
    canvas.drawString(18 * mm, 8 * mm, "数据源：巨潮资讯公开年报")
    canvas.drawRightString(width - 18 * mm, 8 * mm, "1 / 1")
    canvas.restoreState()


def make_styles():
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title",
            parent=styles["Title"],
            fontName="STSong-Light",
            fontSize=21,
            leading=27,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=4,
        ),
        "lead": ParagraphStyle(
            "Lead",
            fontName="STSong-Light",
            fontSize=10.2,
            leading=17,
            textColor=INK,
        ),
        "body": ParagraphStyle(
            "Body",
            fontName="STSong-Light",
            fontSize=8.8,
            leading=14,
            textColor=INK_SOFT,
        ),
        "small": ParagraphStyle(
            "Small",
            fontName="STSong-Light",
            fontSize=7.4,
            leading=11.5,
            textColor=INK_SOFT,
        ),
        "section": ParagraphStyle(
            "Section",
            fontName="STSong-Light",
            fontSize=12.5,
            leading=18,
            textColor=INK,
            spaceBefore=2,
            spaceAfter=5,
        ),
        "metric": ParagraphStyle(
            "Metric",
            fontName="STSong-Light",
            fontSize=20,
            leading=23,
            textColor=INK,
            alignment=1,
        ),
        "metric_label": ParagraphStyle(
            "MetricLabel",
            fontName="STSong-Light",
            fontSize=7.2,
            leading=10,
            textColor=INK_SOFT,
            alignment=1,
        ),
    }


def build_pdf() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = PROJECT_ROOT / "tmp" / "pdfs"
    temp_dir.mkdir(parents=True, exist_ok=True)
    records = json.loads(RESULTS.read_text(encoding="utf-8"))
    correct = sum(record["manual_verdict"] == "正确" for record in records)
    total = len(records)
    evidence_found = sum(
        len(record["found_evidence_keywords"]) for record in records
    )
    evidence_total = sum(
        len(record["evidence_keywords"]) for record in records
    )
    category_counts = Counter(record["category"].split("-")[0] for record in records)

    styles = make_styles()
    doc = BaseDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=48 * mm,
        bottomMargin=19 * mm,
        title="同一批财报，什么该建库？",
        author="Financial Report RAG",
    )
    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="main",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    doc.addPageTemplates(
        [PageTemplate(id="conclusion", frames=[frame], onPage=page_decor)]
    )

    story = []
    story.append(
        Paragraph(
            "结论：这类财报问答应优先建库，而不是把事实写进模型权重。",
            styles["title"],
        )
    )
    story.append(
        Paragraph(
            "可追溯、经常更新、涉及具体数字或跨公司比较的问题，<span color='#A33B32'>"
            "依赖检索证据和结构化计算</span>；固定口吻、格式和问法泛化才适合微调。",
            styles["lead"],
        )
    )
    story.append(Spacer(1, 7 * mm))

    metric_data = [
        [
            Paragraph(f"{total - 1} / {total}", styles["metric"]),
            Paragraph(f"{evidence_found} / {evidence_total}", styles["metric"]),
            Paragraph("100%", styles["metric"]),
        ],
        [
            Paragraph("可人工核验的正确答案", styles["metric_label"]),
            Paragraph("关键证据关键词命中", styles["metric_label"]),
            Paragraph("跨公司题的公司覆盖", styles["metric_label"]),
        ],
    ]
    metric_table = Table(metric_data, colWidths=[58 * mm, 58 * mm, 58 * mm])
    metric_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
            ]
        )
    )
    story.append(metric_table)
    story.append(Spacer(1, 7 * mm))

    result_rows = [
        [
            Paragraph("<b>题型</b>", styles["body"]),
            Paragraph("<b>结果</b>", styles["body"]),
            Paragraph("<b>观察</b>", styles["body"]),
        ],
        [
            Paragraph("单公司事实与表格", styles["body"]),
            Paragraph("6 / 6 正确", styles["body"]),
            Paragraph("主会计表、细分表、审计机构和叙述题均可定位。", styles["body"]),
        ],
        [
            Paragraph("跨公司同口径排序", styles["body"]),
            Paragraph("3 / 3 正确", styles["body"]),
            Paragraph("按公司分别召回主表后统一排序，12 家全覆盖。", styles["body"]),
        ],
        [
            Paragraph("语料外问题", styles["body"]),
            Paragraph("1 / 1 正确", styles["body"]),
            Paragraph("能够拒答 2026 年一季报数据，不越界生成。", styles["body"]),
        ],
        [
            Paragraph("跨公司多跳计算", styles["body"]),
            Paragraph("<font color='#A33B32'>0 / 1 正确</font>", styles["body"]),
            Paragraph("“归母净利率最高”只召回叙述块，未定位收入与利润主表。", styles["body"]),
        ],
    ]
    result_table = Table(
        result_rows,
        colWidths=[43 * mm, 25 * mm, 105 * mm],
        repeatRows=1,
    )
    result_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ECE8DF")),
                ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(result_table)
    story.append(Spacer(1, 7 * mm))

    story.append(Paragraph("为什么翻车", styles["section"]))
    story.append(
        Paragraph(
            "净利率不是原表中的一个字段。系统虽覆盖了 12 家公司，却没有把“营业收入”和"
            "“归母净利润”对齐到同一公司、同一期间的表格行，也没有执行两步运算。"
            "这说明 <b>RAG 解决“找得到依据”，不自动等于“会完成业务计算”</b>。",
            styles["body"],
        )
    )
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("下一步怎么修", styles["section"]))
    plan = Table(
        [
            [
                Paragraph("01  意图解析", styles["body"]),
                Paragraph("识别指标、期间、公司与比较方向，生成“取数 - 计算 - 排序”计划。", styles["body"]),
            ],
            [
                Paragraph("02  结构化取数", styles["body"]),
                Paragraph("把主要会计数据表转成公司-年度-指标的长表，保留页码回链。", styles["body"]),
            ],
            [
                Paragraph("03  计算与复核", styles["body"]),
                Paragraph("由代码执行比率和排名，模型只解释结果；引用仍回到原始表。", styles["body"]),
            ],
        ],
        colWidths=[35 * mm, 138 * mm],
    )
    plan.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.3, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(plan)
    story.append(Spacer(1, 5 * mm))

    footer_note = Table(
        [
            [
                Paragraph(
                    "<font color='#A33B32'><b>适合建库</b></font><br/>"
                    "具体数字、原文依据、跨公司比较、需要页码复核、财报持续更新。",
                    styles["small"],
                ),
                Paragraph(
                    "<font color='#2E665D'><b>才考虑微调</b></font><br/>"
                    "稳定的董秘口吻、固定回复格式、同一套问法的表达泛化。",
                    styles["small"],
                ),
            ]
        ],
        colWidths=[86.5 * mm, 86.5 * mm],
    )
    footer_note.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.append(footer_note)

    doc.build(story)
    print(OUTPUT)


if __name__ == "__main__":
    build_pdf()
