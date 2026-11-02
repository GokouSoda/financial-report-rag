from __future__ import annotations

import csv
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from scripts.answer import answer_question
from scripts.retrieval import HybridRetriever


PROJECT_ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="Financial Report RAG", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    companies: list[str] = Field(default_factory=list)
    top_k: int = Field(default=8, ge=1, le=30)


class QueryResponse(BaseModel):
    answer: str
    mode: Literal["llm", "extractive"]
    results: list[dict]


@lru_cache(maxsize=1)
def get_retriever() -> HybridRetriever:
    return HybridRetriever()


@lru_cache(maxsize=1)
def get_report_urls() -> dict[str, str]:
    manifest = PROJECT_ROOT / "data" / "downloads.csv"
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {row["stock_code"]: row["pdf_url"] for row in rows}


@app.get("/api/health")
def health() -> dict:
    retriever = get_retriever()
    return {
        "status": "ok",
        "companies": retriever.companies,
        "documents": len(retriever.companies),
        "chunks": len(retriever.chunks),
        "embedding_model": retriever.manifest["embedding_model"],
        "llm_configured": bool(
            os.getenv("LLM_BASE_URL") and os.getenv("LLM_MODEL")
        ),
    }


@app.post("/api/query", response_model=QueryResponse)
def query(payload: QueryRequest) -> QueryResponse:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    try:
        retriever = get_retriever()
        results = retriever.search(
            question,
            companies=payload.companies or None,
            top_k=payload.top_k,
        )
        answer, mode = answer_question(question, results)
        report_urls = get_report_urls()
        serialized = []
        for index, result in enumerate(results, start=1):
            item = result.to_dict()
            item["citation"] = index
            item["source_url"] = report_urls.get(item["stock_code"], "")
            serialized.append(item)
        return QueryResponse(answer=answer, mode=mode, results=serialized)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Query failed: {exc}") from exc
