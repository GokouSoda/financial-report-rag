from __future__ import annotations

import argparse

try:
    from answer import answer_question
    from retrieval import HybridRetriever
except ModuleNotFoundError:
    from scripts.answer import answer_question
    from scripts.retrieval import HybridRetriever


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask a cited question over the reports.")
    parser.add_argument("question")
    parser.add_argument("--company", action="append")
    parser.add_argument("--top-k", type=int, default=8)
    args = parser.parse_args()

    retriever = HybridRetriever()
    results = retriever.search(
        args.question,
        companies=args.company,
        top_k=args.top_k,
    )
    answer, mode = answer_question(args.question, results)
    print(answer)
    print(f"\n回答模式：{mode}")
    print("\n出处：")
    for index, result in enumerate(results, start=1):
        chunk = result.chunk
        print(
            f"[{index}] {chunk['company']}《{chunk['report_year']}年年报》"
            f" PDF第{chunk['pdf_page_start']}页"
            f"（报告第{chunk['printed_page_start'] or '?'}页）"
            f" {chunk['chapter']} > {chunk['subsection']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
