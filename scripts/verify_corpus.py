from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from pypdf import PdfReader


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class AuditRecord:
    company: str
    stock_code: str
    file_name: str
    page_count: str
    sample_text_chars: str
    text_layer_status: str
    sha256_status: str
    title_status: str
    audit_status: str
    error: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def audit_one(row: dict[str, str], raw_dir: Path) -> AuditRecord:
    errors: list[str] = []
    path = raw_dir / row["file_name"]
    page_count = ""
    sample_chars = ""
    text_status = "fail"
    checksum_status = "fail"
    title_status = "fail"

    if not path.exists():
        errors.append("file missing")
    else:
        try:
            reader = PdfReader(str(path))
            page_count = str(len(reader.pages))
            if len(reader.pages) < 50:
                errors.append("too few pages")

            sample_indices = {0}
            if len(reader.pages) > 20:
                sample_indices.add(20)
            if len(reader.pages) > 1:
                sample_indices.add(len(reader.pages) - 1)
            sample_text = "\n".join(
                reader.pages[index].extract_text() or ""
                for index in sorted(sample_indices)
            )
            compact_text = "".join(sample_text.split())
            sample_chars = str(len(compact_text))
            if len(compact_text) < 200:
                errors.append("insufficient extractable text")
            else:
                text_status = "pass"

            first_pages = "\n".join(
                reader.pages[index].extract_text() or ""
                for index in range(min(3, len(reader.pages)))
            )
            compact_first = "".join(first_pages.split())
            if row["report_year"] in compact_first and "年度报告" in compact_first:
                title_status = "pass"
            else:
                errors.append("first pages do not identify the expected annual report")
        except Exception as exc:
            errors.append(f"pdf read error: {exc}")

    title = row.get("announcement_title", "").replace(" ", "")
    if any(token in title.lower() for token in ("摘要", "英文", "english")):
        errors.append("announcement is not the Chinese full report")

    if path.exists():
        actual_checksum = sha256_file(path)
        if actual_checksum == row.get("sha256"):
            checksum_status = "pass"
        else:
            errors.append("sha256 mismatch")

    audit_status = "pass" if not errors else "fail"
    return AuditRecord(
        company=row["company"],
        stock_code=row["stock_code"],
        file_name=row["file_name"],
        page_count=page_count,
        sample_text_chars=sample_chars,
        text_layer_status=text_status,
        sha256_status=checksum_status,
        title_status=title_status,
        audit_status=audit_status,
        error="; ".join(errors),
    )


def write_audit(records: list[AuditRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(AuditRecord.__dataclass_fields__)
        )
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit downloaded annual-report PDFs.")
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
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "corpus_audit.csv",
    )
    args = parser.parse_args()

    rows = read_manifest(args.manifest)
    records = [audit_one(row, args.raw_dir) for row in rows]
    write_audit(records, args.output)

    failures = [record for record in records if record.audit_status != "pass"]
    for record in records:
        print(
            f"{record.stock_code} {record.company}: "
            f"{record.audit_status}, {record.page_count} pages"
        )
        if record.error:
            print(f"  {record.error}", file=sys.stderr)

    print(f"\nAudited {len(records)} PDFs; {len(failures)} failed.")
    print(f"Wrote {args.output}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
