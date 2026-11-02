from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from extract_pdf import PROJECT_ROOT, DocumentMeta, extract_report


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract all downloaded annual reports.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT / "data" / "downloads.csv",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "raw",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed",
    )
    args = parser.parse_args()

    rows = read_manifest(args.manifest)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    failures = []

    for index, row in enumerate(rows, start=1):
        label = f"{row['company']} ({row['stock_code']})"
        print(f"[{index}/{len(rows)}] Extracting {label}...")
        pdf_path = args.raw_dir / row["file_name"]
        if not pdf_path.exists():
            failures.append({"company": label, "error": "PDF missing"})
            print("  ERROR: PDF missing")
            continue

        meta = DocumentMeta(
            company=row["company"],
            stock_code=row["stock_code"],
            exchange=row["exchange"],
            report_type=row["report_type"],
            report_year=row["report_year"],
            file_name=row["file_name"],
        )
        stem = f"{meta.stock_code}_{meta.report_year}"
        output = args.output_dir / f"{stem}_blocks.jsonl"
        try:
            stats = extract_report(pdf_path, meta, 1, None, output)
            results.append(stats)
            print(
                f"  {stats['pages_written']} pages, "
                f"{stats['blocks']} blocks, {stats['tables']} tables"
            )
        except Exception as exc:
            failures.append({"company": label, "error": str(exc)})
            print(f"  ERROR: {exc}")

    summary = {
        "documents_expected": len(rows),
        "documents_extracted": len(results),
        "documents_failed": len(failures),
        "pages": sum(item["pages_written"] for item in results),
        "blocks": sum(item["blocks"] for item in results),
        "tables": sum(item["tables"] for item in results),
        "text_blocks": sum(item["text_blocks"] for item in results),
        "heading_blocks": sum(item["heading_blocks"] for item in results),
        "failures": failures,
        "documents": results,
    }
    summary_path = args.output_dir / "extraction_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
