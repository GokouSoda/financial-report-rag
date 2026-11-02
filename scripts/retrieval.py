from __future__ import annotations

import argparse
import json
import os
import pickle
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import faiss
import jieba
import numpy as np
from sentence_transformers import SentenceTransformer

try:
    from build_index import TOKEN_RE, tokenize
except ModuleNotFoundError:
    from scripts.build_index import TOKEN_RE, tokenize


PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
CROSS_COMPANY_TERMS = (
    "哪些公司",
    "哪家公司",
    "哪个公司",
    "比较",
    "排名",
    "最高",
    "最低",
    "各家",
    "各公司",
    "所有公司",
    "分别",
    "全景",
    "白酒行业",
    "12家",
    "十二家",
)
MAIN_METRICS = (
    "营业收入",
    "净利润",
    "总资产",
    "净资产",
    "每股收益",
    "现金流量净额",
    "研发费用",
    "研发投入",
)
METRIC_ALIASES = {
    "营业收入": ("营业收入", "营业总收入"),
    "净利润": ("净利润", "归属于上市公司股东的净利润"),
    "总资产": ("总资产",),
    "净资产": ("净资产", "所有者权益"),
    "每股收益": ("每股收益",),
    "现金流量净额": ("现金流量净额",),
    "研发费用": ("研发费用", "研发投入"),
    "研发投入": ("研发投入",),
}
COMPANY_ALIASES = {
    "贵州茅台": ("贵州茅台", "茅台"),
    "五粮液": ("五粮液",),
    "泸州老窖": ("泸州老窖", "老窖"),
    "山西汾酒": ("山西汾酒", "汾酒"),
    "古井贡酒": ("古井贡酒", "古井"),
    "洋河股份": ("洋河股份", "洋河"),
    "今世缘": ("今世缘",),
    "迎驾贡酒": ("迎驾贡酒", "迎驾"),
    "舍得酒业": ("舍得酒业", "舍得"),
    "水井坊": ("水井坊",),
    "酒鬼酒": ("酒鬼酒", "酒鬼"),
    "口子窖": ("口子窖", "口子"),
}


@dataclass
class SearchResult:
    chunk: dict[str, Any]
    vector_score: float
    bm25_score: float
    vector_rank: int | None
    bm25_rank: int | None
    hybrid_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.chunk,
            "vector_score": round(self.vector_score, 6),
            "bm25_score": round(self.bm25_score, 6),
            "vector_rank": self.vector_rank,
            "bm25_rank": self.bm25_rank,
            "hybrid_score": round(self.hybrid_score, 6),
        }


def detect_companies(query: str, available: Iterable[str]) -> list[str]:
    found = []
    for company in available:
        aliases = COMPANY_ALIASES.get(company, (company,))
        if any(alias in query for alias in aliases):
            found.append(company)
    return found


def asks_for_cross_company(query: str) -> bool:
    return any(term in query for term in CROSS_COMPANY_TERMS)


def asks_for_number(query: str) -> bool:
    return any(
        term in query
        for term in (
            "多少",
            "金额",
            "是多少",
            "几",
            "数值",
            "最高",
            "最低",
            "超过",
            "高于",
            "低于",
            "比较",
            "分别",
            "排名",
        )
    )


def is_primary_metric_query(query: str) -> bool:
    qualifiers = (
        "构成",
        "明细",
        "分类",
        "原因",
        "同比",
        "增减",
        "变化",
        "增长",
        "下降",
        "占比",
        "比例",
        "率",
        "业务",
        "渠道",
        "产品",
        "地区",
        "毛利",
        "直销",
        "批发",
        "国内",
        "国外",
        "主营业务",
    )
    return (
        asks_for_number(query)
        and any(metric in query for metric in MAIN_METRICS)
        and not any(qualifier in query for qualifier in qualifiers)
    )


def ranking_bonus(query: str, chunk: dict[str, Any]) -> float:
    subsection = chunk.get("subsection", "")
    score = 0.0
    content = chunk.get("content", "")
    for metric in MAIN_METRICS:
        if metric not in query:
            continue
        aliases = METRIC_ALIASES.get(metric, (metric,))
        appears_in_table = (
            chunk.get("chunk_type") == "table"
            and any(alias in content for alias in aliases)
            and bool(re.search(r"\d", content))
        )
        is_main_data = any(
            section in subsection
            for section in (
                "主要会计数据",
                "主要财务指标",
                "主要会计数据和财务指标",
            )
        )
        if appears_in_table and is_main_data:
            score += 0.03
        elif appears_in_table:
            score += 0.008
        if is_main_data:
            score += 0.003
    for metric, aliases in METRIC_ALIASES.items():
        if metric in query:
            break
    else:
        aliases = ()
    if (
        asks_for_number(query)
        and chunk.get("chunk_type") == "table"
        and aliases
        and any(alias in content for alias in aliases)
    ):
        score += 0.003
    if asks_for_number(query) and chunk.get("chunk_type") == "table":
        score += 0.0004
    if asks_for_number(query) and not re.search(r"\d", chunk.get("content", "")):
        score -= 0.0005
    if "营业外收入" in subsection and "营业外收入" not in query:
        score -= 0.0005
    if chunk.get("pdf_page_start", 99) <= 4:
        score -= 0.004
    if (
        "风险" in query
        and "风险" in subsection
        and chunk.get("pdf_page_start", 0) > 4
        and len(content) > 40
    ):
        score += 0.04
    if "研发费用" in query or "研发投入" in query:
        if chunk.get("chunk_type") == "table":
            if any(
                phrase in content
                for phrase in ("研发投入合计", "研发投入金额")
            ):
                score += 0.04
            if any(phrase in content for phrase in ("资本化", "占营业收入比例")):
                score -= 0.002
    if any(term in query for term in ("直销", "批发", "销售渠道")):
        if any(
            phrase in subsection
            for phrase in ("分销售模式", "主营业务构成")
        ):
            score += 0.05
    return score


def reciprocal_rank_fusion(
    vector_ranking: list[int],
    bm25_ranking: list[int],
    rrf_k: int = 60,
) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranking in (vector_ranking, bm25_ranking):
        for rank, index in enumerate(ranking, start=1):
            scores[index] = scores.get(index, 0.0) + 1.0 / (rrf_k + rank)
    return scores


class HybridRetriever:
    def __init__(
        self,
        index_dir: Path | None = None,
        load_embedding_model: bool = True,
    ) -> None:
        self.index_dir = (index_dir or PROJECT_ROOT / "data" / "index").resolve()
        manifest_path = self.index_dir / "index_manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"Index not found at {self.index_dir}. Run scripts/build_index.py first."
            )
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.chunks = [
            json.loads(line)
            for line in (self.index_dir / "chunks.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        self.embeddings = np.load(
            self.index_dir / "embeddings.npy",
            mmap_mode="r",
        ).astype(np.float32)
        serialized_index = np.load(self.index_dir / "vectors.faiss.npy")
        self.vector_index = faiss.deserialize_index(serialized_index)
        with (self.index_dir / "bm25.pkl").open("rb") as handle:
            self.bm25 = pickle.load(handle)

        self.companies = self.manifest["companies"]
        self.indices_by_company = {
            company: np.asarray(
                [
                    index
                    for index, chunk in enumerate(self.chunks)
                    if chunk["company"] == company
                ],
                dtype=np.int64,
            )
            for company in self.companies
        }
        self.model = None
        if load_embedding_model:
            self.model = SentenceTransformer(
                self.manifest["embedding_model"],
                device="cpu",
            )

    def encode_query(self, query: str) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("The embedding model is not loaded")
        vector = self.model.encode(
            [QUERY_INSTRUCTION + query],
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype(np.float32)
        return vector[0]

    def _vector_scores_for_indices(
        self,
        query_vector: np.ndarray,
        indices: np.ndarray,
    ) -> np.ndarray:
        return np.asarray(
            [float(np.dot(query_vector, self.embeddings[index])) for index in indices]
        )

    def _search_subset(
        self,
        query: str,
        query_vector: np.ndarray,
        indices: np.ndarray,
        candidate_k: int,
    ) -> list[SearchResult]:
        if not len(indices):
            return []

        vector_scores = self._vector_scores_for_indices(query_vector, indices)
        vector_order = np.argsort(-vector_scores)[:candidate_k]
        vector_indices = [int(indices[position]) for position in vector_order]

        all_bm25_scores = np.asarray(self.bm25.get_scores(tokenize(query)))
        subset_bm25 = all_bm25_scores[indices]
        bm25_order = np.argsort(-subset_bm25)[:candidate_k]
        bm25_indices = [int(indices[position]) for position in bm25_order]

        fused = reciprocal_rank_fusion(vector_indices, bm25_indices)
        if "风险" in query:
            for index in indices:
                chunk = self.chunks[int(index)]
                if "可能面对的风险" in chunk.get("subsection", ""):
                    fused[int(index)] = max(fused.get(int(index), 0.0), 0.07)
        if any(term in query for term in ("审计机构", "会计师事务所")):
            for index in indices:
                chunk = self.chunks[int(index)]
                if "会计师事务所" in chunk.get("content", ""):
                    fused[int(index)] = max(fused.get(int(index), 0.0), 0.08)
        if is_primary_metric_query(query):
            for index in indices:
                chunk = self.chunks[int(index)]
                if chunk.get("chunk_type") != "table":
                    continue
                if not any(
                    section in chunk.get("subsection", "")
                    for section in (
                        "主要会计数据",
                        "主要财务指标",
                        "主要会计数据和财务指标",
                    )
                ):
                    continue
                if any(
                    alias in chunk.get("content", "")
                    for metric in MAIN_METRICS
                    if metric in query
                    for alias in METRIC_ALIASES.get(metric, (metric,))
                ):
                    fused[int(index)] = max(fused.get(int(index), 0.0), 0.04)
        vector_rank = {index: rank for rank, index in enumerate(vector_indices, 1)}
        bm25_rank = {index: rank for rank, index in enumerate(bm25_indices, 1)}
        ordered_indices = sorted(
            fused,
            key=lambda index: (
                fused[index],
                vector_rank.get(index, candidate_k + 1),
            ),
            reverse=True,
        )

        results = []
        for index in ordered_indices:
            chunk = self.chunks[index]
            results.append(
                SearchResult(
                    chunk=chunk,
                    vector_score=float(
                        vector_scores[np.where(indices == index)[0][0]]
                    ),
                    bm25_score=float(all_bm25_scores[index]),
                    vector_rank=vector_rank.get(index),
                    bm25_rank=bm25_rank.get(index),
                    hybrid_score=fused[index] + ranking_bonus(query, chunk),
                )
            )
        results.sort(key=lambda result: result.hybrid_score, reverse=True)
        return results

    def search(
        self,
        query: str,
        companies: Iterable[str] | None = None,
        top_k: int = 8,
        candidate_k: int = 40,
    ) -> list[SearchResult]:
        query = query.strip()
        if not query:
            return []

        explicit_companies = detect_companies(query, self.companies)
        if companies:
            selected = [company for company in companies if company in self.companies]
        elif explicit_companies:
            selected = explicit_companies
        else:
            selected = []

        query_vector = self.encode_query(query)
        cross_company = asks_for_cross_company(query) or len(selected) > 1
        if cross_company and not selected:
            selected = list(self.companies)

        if selected:
            indices = np.concatenate(
                [self.indices_by_company[company] for company in selected]
            )
        else:
            indices = np.arange(len(self.chunks), dtype=np.int64)

        if not cross_company:
            return self._search_subset(
                query, query_vector, indices, candidate_k
            )[:top_k]

        per_company_results = []
        for company in selected:
            company_results = self._search_subset(
                query,
                query_vector,
                self.indices_by_company[company],
                candidate_k=max(10, candidate_k // max(1, len(selected))),
            )
            if company_results:
                per_company_results.append(company_results[0])
        return sorted(
            per_company_results,
            key=lambda result: result.hybrid_score,
            reverse=True,
        )[: max(top_k, len(per_company_results))]


def display_result(index: int, result: SearchResult) -> str:
    chunk = result.chunk
    return (
        f"[{index}] {chunk['company']}《{chunk['report_year']}年年报》"
        f" PDF第{chunk['pdf_page_start']}页 / 报告第"
        f"{chunk['printed_page_start'] or '?'}页\n"
        f"    {chunk['chapter']} > {chunk['subsection']}\n"
        f"    hybrid={result.hybrid_score:.5f} "
        f"vector_rank={result.vector_rank} bm25_rank={result.bm25_rank}\n"
        f"    {chunk['content'][:300].replace(chr(10), ' ')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Query the hybrid report index.")
    parser.add_argument("query")
    parser.add_argument("--company", action="append")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    retriever = HybridRetriever()
    results = retriever.search(
        args.query,
        companies=args.company,
        top_k=args.top_k,
    )
    if args.json:
        print(
            json.dumps(
                [result.to_dict() for result in results],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for index, result in enumerate(results, start=1):
            print(display_result(index, result))
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
