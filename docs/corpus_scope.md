# Corpus scope

## Decision

The first version uses the 2025 annual reports of 12 listed Chinese liquor companies:

| Company | Code | Exchange |
|---|---:|---|
| 贵州茅台 | 600519 | SSE |
| 五粮液 | 000858 | SZSE |
| 泸州老窖 | 000568 | SZSE |
| 山西汾酒 | 600809 | SSE |
| 古井贡酒 | 000596 | SZSE |
| 洋河股份 | 002304 | SZSE |
| 今世缘 | 603369 | SSE |
| 迎驾贡酒 | 603198 | SSE |
| 舍得酒业 | 600702 | SSE |
| 水井坊 | 600779 | SSE |
| 酒鬼酒 | 000799 | SZSE |
| 口子窖 | 603589 | SSE |

The extra two companies provide a buffer above the 10-company requirement while keeping the corpus small enough for reliable manual evaluation.

## Inclusion rules

- One report type and one fiscal year across all companies.
- Full annual report, not an annual report summary.
- Chinese-language report, not an English translation.
- The latest matching full-report announcement returned by CNINFO is used, so a later corrected report takes precedence over an earlier version.

## Provenance rules

`data/downloads.csv` records the stock code, announcement ID, announcement date, source URL, local file name, file size, SHA-256, and download status. PDFs remain under ignored `data/raw/`.

The document page and PDF page will be stored separately in later extraction stages because annual reports can have a cover, table of contents, and printed page numbering that do not match the PDF index.

