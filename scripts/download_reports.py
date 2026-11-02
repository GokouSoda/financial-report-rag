from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CNINFO_BASE = "https://www.cninfo.com.cn"
CNINFO_STATIC = "https://static.cninfo.com.cn"
SEARCH_URL = f"{CNINFO_BASE}/new/information/topSearch/query"
ANNOUNCEMENT_URL = f"{CNINFO_BASE}/new/hisAnnouncement/query"


@dataclass
class ReportRecord:
    company: str
    stock_code: str
    exchange: str
    report_type: str
    report_year: str
    announcement_date: str
    announcement_title: str
    announcement_id: str
    pdf_url: str
    file_name: str
    announced_size_kb: str
    actual_size_bytes: str
    sha256: str
    download_status: str


def make_session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Referer": f"{CNINFO_BASE}/",
        }
    )
    return session


def read_companies(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {"company", "stock_code", "exchange", "report_type", "report_year"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"{path} must contain columns: {sorted(required)}")
    return rows


def lookup_org_id(session: requests.Session, stock_code: str) -> tuple[str, str]:
    response = session.post(
        SEARCH_URL,
        data={"keyWord": stock_code, "maxNum": "10"},
        timeout=30,
    )
    response.raise_for_status()
    matches = response.json()
    for item in matches:
        if item.get("code") == stock_code and item.get("orgId"):
            return item["orgId"], item.get("zwjc", "")
    raise RuntimeError(f"CNINFO did not return an organization ID for {stock_code}")


def is_full_annual_report(title: str, report_year: str) -> bool:
    normalized = title.replace(" ", "").lower()
    excluded = ("摘要", "英文", "english", "已取消", "取消")
    if report_year not in normalized:
        return False
    if any(token in normalized for token in excluded):
        return False
    return "年度报告" in normalized or "年报" in normalized


def query_report(
    session: requests.Session, company: dict[str, str]
) -> tuple[dict[str, Any], str]:
    stock_code = company["stock_code"]
    org_id, _ = lookup_org_id(session, stock_code)
    is_sse = company["exchange"].upper() == "SSE"
    report_year = company["report_year"]

    payload = {
        "pageNum": "1",
        "pageSize": "30",
        "column": "sse" if is_sse else "szse",
        "tabName": "fulltext",
        "plate": "sh" if is_sse else "sz",
        "stock": f"{stock_code},{org_id}",
        "searchkey": "",
        "secid": "",
        "category": "category_ndbg_szsh",
        "trade": "",
        "seDate": f"{report_year}-01-01~{int(report_year) + 1}-12-31",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    response = session.post(ANNOUNCEMENT_URL, data=payload, timeout=30)
    response.raise_for_status()
    announcements = response.json().get("announcements") or []

    candidates = [
        item
        for item in announcements
        if is_full_annual_report(item.get("announcementTitle", ""), report_year)
    ]
    if not candidates:
        raise RuntimeError(
            f"No full {report_year} annual report found for "
            f"{company['company']} ({stock_code})"
        )

    candidates.sort(
        key=lambda item: (
            item.get("announcementTime") or 0,
            item.get("announcementId") or "",
        ),
        reverse=True,
    )
    return candidates[0], org_id


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_pdf(path: Path) -> int:
    if not path.exists() or path.stat().st_size < 8:
        raise ValueError(f"Downloaded file is missing or too small: {path}")
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise ValueError(f"Downloaded file is not a PDF: {path}")
    return path.stat().st_size


def download_pdf(
    session: requests.Session,
    url: str,
    destination: Path,
    force: bool,
) -> tuple[int, str, str]:
    if destination.exists() and not force:
        size = verify_pdf(destination)
        return size, sha256_file(destination), "already_downloaded"

    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f"{destination.name}.",
        suffix=".part",
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)

    try:
        with session.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            with temporary_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)

        size = verify_pdf(temporary_path)
        os.replace(temporary_path, destination)
        return size, sha256_file(destination), "downloaded"
    finally:
        temporary_path.unlink(missing_ok=True)


def announcement_date(item: dict[str, Any]) -> str:
    timestamp = item.get("announcementTime")
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp / 1000).astimezone().date().isoformat()


def write_manifest(records: list[ReportRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(ReportRecord.__dataclass_fields__)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download 2025 full annual reports from CNINFO."
    )
    parser.add_argument(
        "--companies",
        type=Path,
        default=PROJECT_ROOT / "data" / "companies.csv",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT / "data" / "downloads.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "raw",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Resolve announcements and write the manifest without downloading PDFs.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Redownload PDFs even when a local copy exists.",
    )
    args = parser.parse_args()

    companies = read_companies(args.companies)
    session = make_session()
    records: list[ReportRecord] = []
    failures = 0

    for index, company in enumerate(companies, start=1):
        label = f"{company['company']} ({company['stock_code']})"
        print(f"[{index}/{len(companies)}] Looking up {label}...")
        try:
            announcement, _ = query_report(session, company)
            relative_url = announcement["adjunctUrl"].lstrip("/")
            pdf_url = f"{CNINFO_STATIC}/{relative_url}"
            file_name = (
                f"{company['stock_code']}_{company['report_year']}_annual.pdf"
            )
            actual_size = ""
            checksum = ""
            status = "metadata_only"

            if not args.metadata_only:
                actual_size_int, checksum, status = download_pdf(
                    session,
                    pdf_url,
                    args.output_dir / file_name,
                    args.force,
                )
                actual_size = str(actual_size_int)

            record = ReportRecord(
                company=company["company"],
                stock_code=company["stock_code"],
                exchange=company["exchange"],
                report_type=company["report_type"],
                report_year=company["report_year"],
                announcement_date=announcement_date(announcement),
                announcement_title=announcement.get("announcementTitle", ""),
                announcement_id=str(announcement.get("announcementId", "")),
                pdf_url=pdf_url,
                file_name=file_name,
                announced_size_kb=str(announcement.get("adjunctSize", "")),
                actual_size_bytes=actual_size,
                sha256=checksum,
                download_status=status,
            )
            records.append(record)
            print(
                f"  {announcement.get('announcementTitle')} | "
                f"{record.announcement_date} | {status}"
            )
        except Exception as exc:
            failures += 1
            print(f"  ERROR: {exc}", file=sys.stderr)
        time.sleep(0.35)

    write_manifest(records, args.manifest)
    print(f"\nWrote {len(records)} records to {args.manifest}")
    if failures:
        print(f"{failures} company lookup/download(s) failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
