from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

try:
    from answer import answer_question
    from retrieval import HybridRetriever
except ModuleNotFoundError:
    from scripts.answer import answer_question
    from scripts.retrieval import HybridRetriever


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fixed 10-question evaluation.")
    parser.add_argument(
        "--questions",
        type=Path,
        default=PROJECT_ROOT / "eval" / "questions.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "eval" / "results.json",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=PROJECT_ROOT / "eval" / "results.csv",
    )
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument(
        "--reviews",
        type=Path,
        default=PROJECT_ROOT / "eval" / "manual_reviews.json",
    )
    args = parser.parse_args()

    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    reviews = (
        json.loads(args.reviews.read_text(encoding="utf-8"))
        if args.reviews.exists()
        else {}
    )
    retriever = HybridRetriever()
    records = []

    for question in questions:
        started = time.perf_counter()
        results = retriever.search(
            question["question"],
            companies=question.get("companies") or None,
            top_k=args.top_k,
        )
        answer, mode = answer_question(question["question"], results)
        elapsed = time.perf_counter() - started

        retrieved_companies = sorted({result.chunk["company"] for result in results})
        required_companies = question["required_companies"]
        covered_companies = [
            company for company in required_companies if company in retrieved_companies
        ]
        missing_companies = [
            company for company in required_companies if company not in retrieved_companies
        ]

        result_text = "\n".join(result.chunk["content"] for result in results)
        found_evidence = [
            keyword
            for keyword in question["evidence_keywords"]
            if keyword in result_text
        ]
        missing_evidence = [
            keyword
            for keyword in question["evidence_keywords"]
            if keyword not in result_text
        ]
        answer_keywords_found = [
            keyword
            for keyword in question["answer_keywords"]
            if keyword in answer
        ]

        record = {
            **question,
            "manual_verdict": reviews.get(question["id"], {}).get("verdict", ""),
            "error_notes": reviews.get(question["id"], {}).get("notes", ""),
            "answer": answer,
            "answer_mode": mode,
            "latency_seconds": round(elapsed, 3),
            "retrieved_companies": retrieved_companies,
            "covered_companies": covered_companies,
            "missing_companies": missing_companies,
            "company_coverage": (
                round(len(covered_companies) / len(required_companies), 3)
                if required_companies
                else 1.0
            ),
            "found_evidence_keywords": found_evidence,
            "missing_evidence_keywords": missing_evidence,
            "answer_keywords_found": answer_keywords_found,
            "retrieved_chunks": [
                {
                    "chunk_id": result.chunk["chunk_id"],
                    "company": result.chunk["company"],
                    "pdf_page": result.chunk["pdf_page_start"],
                    "printed_page": result.chunk["printed_page_start"],
                    "chapter": result.chunk["chapter"],
                    "subsection": result.chunk["subsection"],
                    "chunk_type": result.chunk["chunk_type"],
                    "content": result.chunk["content"],
                    "hybrid_score": result.hybrid_score,
                    "vector_rank": result.vector_rank,
                    "bm25_rank": result.bm25_rank,
                }
                for result in results
            ],
        }
        records.append(record)
        print(
            f"{question['id']} | coverage={record['company_coverage']:.0%} | "
            f"evidence={len(found_evidence)}/{len(question['evidence_keywords'])} | "
            f"answer={len(answer_keywords_found)}/{len(question['answer_keywords'])} | "
            f"{elapsed:.2f}s"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    fieldnames = [
        "id",
        "category",
        "question",
        "reference_answer",
        "answer",
        "answer_mode",
        "latency_seconds",
        "company_coverage",
        "retrieved_companies",
        "missing_companies",
        "found_evidence_keywords",
        "missing_evidence_keywords",
        "answer_keywords_found",
        "retrieved_chunk_ids",
        "manual_verdict",
        "error_notes",
    ]
    with args.csv_output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "id": record["id"],
                    "category": record["category"],
                    "question": record["question"],
                    "reference_answer": record["reference_answer"],
                    "answer": record["answer"],
                    "answer_mode": record["answer_mode"],
                    "latency_seconds": record["latency_seconds"],
                    "company_coverage": record["company_coverage"],
                    "retrieved_companies": "；".join(record["retrieved_companies"]),
                    "missing_companies": "；".join(record["missing_companies"]),
                    "found_evidence_keywords": "；".join(
                        record["found_evidence_keywords"]
                    ),
                    "missing_evidence_keywords": "；".join(
                        record["missing_evidence_keywords"]
                    ),
                    "answer_keywords_found": "；".join(
                        record["answer_keywords_found"]
                    ),
                    "retrieved_chunk_ids": "；".join(
                        chunk["chunk_id"] for chunk in record["retrieved_chunks"]
                    ),
                    "manual_verdict": record["manual_verdict"],
                    "error_notes": record["error_notes"],
                }
            )

    print(f"\nWrote {args.output}")
    print(f"Wrote {args.csv_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
