from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from extract_pdf import rows_to_markdown


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def context_prefix(block: dict[str, Any]) -> str:
    report_type = "年报" if block["report_type"] == "annual" else block["report_type"]
    parts = [
        f"公司：{block['company']}（{block['stock_code']}）",
        f"报告：{block['report_year']}年{report_type}",
    ]
    if block.get("chapter"):
        parts.append(f"章节：{block['chapter']}")
    if block.get("subsection"):
        parts.append(f"小节：{block['subsection']}")
    return "\n".join(parts)


def make_chunk_id(block: dict[str, Any], sequence: int, part: int = 1) -> str:
    return (
        f"{block['stock_code']}_{block['report_year']}_"
        f"p{block['pdf_page']:03d}_c{sequence:04d}_{part:02d}"
    )


def base_metadata(block: dict[str, Any], chunk_type: str) -> dict[str, Any]:
    return {
        "company": block["company"],
        "stock_code": block["stock_code"],
        "report_type": block["report_type"],
        "report_year": block["report_year"],
        "chapter": block.get("chapter", ""),
        "subsection": block.get("subsection", ""),
        "pdf_page_start": block["pdf_page"],
        "pdf_page_end": block["pdf_page"],
        "printed_page_start": block.get("printed_page", ""),
        "printed_page_end": block.get("printed_page", ""),
        "chunk_type": chunk_type,
    }


def page_chunks(
    page_blocks: list[dict[str, Any]],
    max_chars: int,
    overlap_chars: int,
    sequence: int,
) -> list[dict[str, Any]]:
    chunks = []
    buffer: list[str] = []
    block_ids: set[str] = set()
    current_section: tuple[str, str] | None = None

    def flush(keep_overlap: bool = False) -> None:
        nonlocal buffer, block_ids, sequence
        body = "\n".join(part for part in buffer if part).strip()
        if not body or not block_ids:
            buffer = []
            block_ids = set()
            return
        anchor = next(
            block for block in page_blocks if block["block_id"] in block_ids
        )
        sequence += 1
        chunk = base_metadata(anchor, "text")
        chunk.update(
            {
                "chunk_id": make_chunk_id(anchor, sequence),
                "block_ids": sorted(block_ids),
                "content": f"{context_prefix(anchor)}\n正文：\n{body}",
                "text": body,
            }
        )
        chunks.append(chunk)
        buffer = (
            [body[-overlap_chars:]]
            if keep_overlap and overlap_chars and body
            else []
        )
        block_ids = set()

    for block in page_blocks:
        block_type = block["type"]
        if block_type == "table":
            flush(keep_overlap=False)
            current_section = None
            sequence += 1
            chunks.extend(
                table_chunks(
                    block,
                    max_chars=max_chars * 2,
                    sequence=sequence,
                )
            )
            continue

        section = (block.get("chapter", ""), block.get("subsection", ""))
        text = block.get("text", "").strip()
        if not text:
            continue

        if current_section is not None and section != current_section:
            flush(keep_overlap=False)
        current_section = section

        projected = len("\n".join([*buffer, text]))
        if buffer and projected > max_chars:
            flush(keep_overlap=True)
            if block_type != "heading":
                buffer.append(context_prefix(block))
        buffer.append(text)
        if block_type == "text":
            block_ids.add(block["block_id"])

    flush(keep_overlap=False)
    return chunks, sequence


def table_chunks(
    block: dict[str, Any],
    max_chars: int,
    sequence: int,
) -> list[dict[str, Any]]:
    rows = block.get("rows", [])
    if not rows:
        return []

    chunks = []
    header = rows[0]
    start = 1
    part = 1

    while start < len(rows):
        section_rows = [header]
        end = start
        while end < len(rows):
            candidate = section_rows + [rows[end]]
            if len(rows_to_markdown(candidate)) + len(context_prefix(block)) > max_chars:
                if len(section_rows) == 1:
                    section_rows.append(rows[end])
                    end += 1
                break
            section_rows.append(rows[end])
            end += 1

        chunk = base_metadata(block, "table")
        caption = block.get("caption", "")
        chunk.update(
            {
                "chunk_id": make_chunk_id(block, sequence, part),
                "block_ids": [block["block_id"]],
                "table_index": block.get("table_index"),
                "table_caption": caption,
                "table_row_start": start,
                "table_row_end": end,
                "rows": section_rows,
                "content": (
                    f"{context_prefix(block)}\n"
                    f"表格：{caption or block.get('subsection', '')}\n"
                    f"{rows_to_markdown(section_rows)}"
                ),
            }
        )
        chunks.append(chunk)
        part += 1
        start = end

    return chunks


def chunk_document(
    blocks: list[dict[str, Any]],
    max_chars: int,
    overlap_chars: int,
) -> list[dict[str, Any]]:
    chunks = []
    pages: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        pages[block["pdf_page"]].append(block)

    sequence = 0
    for pdf_page in sorted(pages):
        page_blocks = pages[pdf_page]
        page_result, sequence = page_chunks(
            page_blocks,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
            sequence=sequence,
        )
        chunks.extend(page_result)
    return chunks


def read_blocks(paths: Iterable[Path]) -> dict[str, list[dict[str, Any]]]:
    documents: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(paths):
        if path.name.endswith("_sample_blocks.jsonl"):
            continue
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not rows:
            continue
        key = rows[0]["document_file"]
        documents[key] = rows
    return documents


def summarize(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    lengths = [len(chunk["content"]) for chunk in chunks]
    by_company = Counter(chunk["company"] for chunk in chunks)
    by_type = Counter(chunk["chunk_type"] for chunk in chunks)
    pages = sum(
        len({chunk["pdf_page_start"] for chunk in chunks if chunk["company"] == company})
        for company in by_company
    )
    return {
        "chunks": len(chunks),
        "by_type": dict(sorted(by_type.items())),
        "by_company": dict(sorted(by_company.items())),
        "pages_covered_by_company_sum": pages,
        "min_chars": min(lengths) if lengths else 0,
        "mean_chars": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "max_chars": max(lengths) if lengths else 0,
        "chunks_without_page": sum(not chunk["pdf_page_start"] for chunk in chunks),
        "chunks_without_company": sum(not chunk["company"] for chunk in chunks),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create section-aware text and table chunks."
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "chunks.jsonl",
    )
    parser.add_argument("--max-chars", type=int, default=800)
    parser.add_argument("--overlap-chars", type=int, default=80)
    args = parser.parse_args()

    documents = read_blocks(args.processed_dir.glob("*_blocks.jsonl"))
    chunks = []
    document_stats = []
    for document_file, blocks in documents.items():
        document_chunks = chunk_document(
            blocks,
            max_chars=args.max_chars,
            overlap_chars=args.overlap_chars,
        )
        chunks.extend(document_chunks)
        document_stats.append(
            {
                "document_file": document_file,
                "company": blocks[0]["company"],
                "blocks": len(blocks),
                "chunks": len(document_chunks),
                "tables": sum(block["type"] == "table" for block in blocks),
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    summary = summarize(chunks)
    summary["documents"] = sorted(document_stats, key=lambda item: item["company"])
    summary_path = args.output.with_name("chunk_summary.json")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
