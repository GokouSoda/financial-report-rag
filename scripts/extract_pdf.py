from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pdfplumber


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "downloads.csv"
CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百]+节\s*")
SUBSECTION_RE = re.compile(
    r"^(?:"
    r"[一二三四五六七八九十]+、|"
    r"（[一二三四五六七八九十]+）|"
    r"\([一二三四五六七八九十]+\)|"
    r"\d+、|"
    r"\(\d+\)[.、]|"
    r"[A-Z]\.\s*"
    r")"
)
PRINTED_PAGE_RE = re.compile(
    r"^(?:第)?(\d+)(?:/\d+|页(?:共\d+页)?)?$"
)


@dataclass
class DocumentMeta:
    company: str
    stock_code: str
    exchange: str
    report_type: str
    report_year: str
    file_name: str


def load_meta(manifest: Path, pdf_path: Path) -> DocumentMeta:
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row["file_name"] == pdf_path.name:
            return DocumentMeta(
                company=row["company"],
                stock_code=row["stock_code"],
                exchange=row["exchange"],
                report_type=row["report_type"],
                report_year=row["report_year"],
                file_name=row["file_name"],
            )
    raise ValueError(f"{pdf_path.name} is not present in {manifest}")


def clean_cell(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s*\n\s*", "\n", value).strip()


def normalize_rows(raw_rows: Iterable[list[str | None]]) -> list[list[str]]:
    rows = [[clean_cell(cell) for cell in row] for row in raw_rows]
    if not rows:
        return []
    width = max(len(row) for row in rows)
    return [row + [""] * (width - len(row)) for row in rows]


def rows_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)

    def render(row: list[str]) -> str:
        cells = [cell.replace("|", r"\|").replace("\n", "<br>") for cell in row]
        return "| " + " | ".join(cells + [""] * (width - len(cells))) + " |"

    header = render(rows[0])
    divider = "| " + " | ".join(["---"] * width) + " |"
    body = [render(row) for row in rows[1:]]
    return "\n".join([header, divider, *body])


def line_is_heading(text: str) -> tuple[bool, str]:
    compact = text.strip()
    if CHAPTER_RE.match(compact):
        return True, "chapter"
    if SUBSECTION_RE.match(compact) and len(compact) <= 120:
        return True, "subsection"
    return False, ""


def is_repeated_header(text: str, meta: DocumentMeta, top: float) -> bool:
    compact = "".join(text.split())
    if top > 65:
        return False
    return (
        meta.company in compact
        and meta.report_year in compact
        and ("年度报告" in compact or "年报" in compact)
    )


def parse_printed_page(text: str, top: float, page_height: float) -> str:
    if top < page_height - 100:
        return ""
    compact = "".join(text.split()).strip("~—-")
    match = PRINTED_PAGE_RE.match(compact)
    return match.group(1) if match else ""


def table_caption(events: list[dict[str, Any]], table_top: float) -> str:
    candidate = ""
    for event in events:
        if event["top"] >= table_top - 2:
            break
        if event["type"] not in {"text", "heading"}:
            continue
        text = event["text"].strip()
        if (
            len(text) <= 160
            and any(
                token in text
                for token in ("表", "情况", "指标", "数据", "分析", "资料")
            )
        ):
            candidate = text
    return candidate


def page_events(
    page: Any,
    meta: DocumentMeta,
    pdf_page: int,
    chapter: str,
    subsection: str,
) -> tuple[list[dict[str, Any]], str, str, str, int]:
    found_tables = page.find_tables()
    table_boxes = [table.bbox for table in found_tables]

    def outside_tables(obj: dict[str, Any]) -> bool:
        top = obj.get("top", 0)
        bottom = obj.get("bottom", 0)
        return not any(
            top >= bbox[1] - 1 and bottom <= bbox[3] + 1
            for bbox in table_boxes
        )

    filtered_page = page.filter(outside_tables)
    text_lines = filtered_page.extract_text_lines(return_chars=True)
    raw_page_text = filtered_page.extract_text() or ""
    is_toc = "目录" in raw_page_text[:500] and len(
        CHAPTER_RE.findall(raw_page_text)
    ) > 2

    events: list[dict[str, Any]] = []
    printed_page = ""
    for line in text_lines:
        text = line["text"].strip()
        if not text:
            continue
        printed_candidate = parse_printed_page(text, line["top"], page.height)
        if printed_candidate:
            printed_page = printed_candidate
            continue
        if is_repeated_header(text, meta, line["top"]):
            continue

        heading, heading_type = line_is_heading(text)
        events.append(
            {
                "top": line["top"],
                "type": "heading" if heading else "text",
                "heading_type": heading_type,
                "text": text,
                "page_width": round(page.width, 2),
                "page_height": round(page.height, 2),
            }
        )

    emitted_tables = 0
    for table_index, table in enumerate(found_tables, start=1):
        rows = normalize_rows(table.extract())
        if not rows or not any(any(cell for cell in row) for row in rows):
            continue
        emitted_tables += 1
        events.append(
            {
                "top": table.bbox[1],
                "type": "table",
                "table_index": table_index,
                "bbox": [round(value, 2) for value in table.bbox],
                "rows": rows,
                "markdown": rows_to_markdown(rows),
            }
        )

    events.sort(key=lambda event: (event["top"], event["type"] == "table"))
    for index, event in enumerate(events, start=1):
        event["block_id"] = f"{meta.stock_code}_{meta.report_year}_p{pdf_page:03d}_{index:02d}"
        event["company"] = meta.company
        event["stock_code"] = meta.stock_code
        event["report_type"] = meta.report_type
        event["report_year"] = meta.report_year
        event["pdf_page"] = pdf_page
        event["printed_page"] = printed_page
        event["document_file"] = meta.file_name
        event["chapter_before"] = chapter
        event["subsection_before"] = subsection

        if event["type"] == "heading":
            if event["heading_type"] == "chapter":
                chapter = event["text"]
                subsection = ""
            else:
                subsection = event["text"]
        event["chapter"] = chapter
        event["subsection"] = subsection

    for event in events:
        if event["type"] == "table":
            event["caption"] = table_caption(events, event["top"])

    return events, chapter, subsection, printed_page, emitted_tables


def extract_report(
    pdf_path: Path,
    meta: DocumentMeta,
    page_start: int,
    page_end: int | None,
    output: Path,
) -> dict[str, Any]:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    stats = {
        "pdf_pages_seen": 0,
        "pages_written": 0,
        "text_blocks": 0,
        "heading_blocks": 0,
        "tables": 0,
        "blocks": 0,
        "empty_pages": 0,
    }
    chapter = ""
    subsection = ""
    last_printed_page = ""

    with pdfplumber.open(pdf_path) as pdf:
        if page_end is None:
            page_end = len(pdf.pages)
        if not (1 <= page_start <= page_end <= len(pdf.pages)):
            raise ValueError(
                f"Invalid page range {page_start}-{page_end}; "
                f"document has {len(pdf.pages)} pages"
            )

        with output.open("w", encoding="utf-8", newline="\n") as handle:
            for pdf_page in range(page_start, page_end + 1):
                stats["pdf_pages_seen"] += 1
                events, chapter, subsection, printed_page, table_count = page_events(
                    pdf.pages[pdf_page - 1],
                    meta,
                    pdf_page,
                    chapter,
                    subsection,
                )
                if printed_page:
                    last_printed_page = printed_page
                if not events:
                    stats["empty_pages"] += 1
                    continue

                stats["pages_written"] += 1
                for event in events:
                    event["printed_page"] = event["printed_page"] or last_printed_page
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                    stats["blocks"] += 1
                    if event["type"] == "text":
                        stats["text_blocks"] += 1
                    elif event["type"] == "heading":
                        stats["heading_blocks"] += 1
                stats["tables"] += table_count

    stats.update(
        {
            "document_file": meta.file_name,
            "company": meta.company,
            "stock_code": meta.stock_code,
            "report_year": meta.report_year,
            "pdf_page_start": page_start,
            "pdf_page_end": page_end,
            "output_file": str(output.relative_to(PROJECT_ROOT)),
        }
    )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract text, headings, printed pages, and tables from a filing."
    )
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--audit-output", type=Path)
    parser.add_argument("--page-start", type=int, default=1)
    parser.add_argument("--page-end", type=int)
    args = parser.parse_args()

    pdf_path = args.pdf.resolve()
    meta = load_meta(args.manifest.resolve(), pdf_path)
    stem = f"{meta.stock_code}_{meta.report_year}"
    output = args.output or PROJECT_ROOT / "data" / "processed" / f"{stem}_blocks.jsonl"
    audit_output = (
        args.audit_output
        or PROJECT_ROOT / "data" / "processed" / f"{stem}_extraction_audit.json"
    )

    stats = extract_report(
        pdf_path,
        meta,
        args.page_start,
        args.page_end,
        output,
    )
    audit_output.parent.mkdir(parents=True, exist_ok=True)
    audit_output.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
