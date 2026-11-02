from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import faiss
import jieba
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z]+|\d+(?:[.,]\d+)*%?")


def load_chunks(path: Path) -> list[dict[str, Any]]:
    chunks = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not chunks:
        raise ValueError(f"No chunks found in {path}")
    return chunks


def tokenize(text: str) -> list[str]:
    normalized = text.lower().replace("\n", " ")
    tokens: list[str] = []
    for piece in TOKEN_RE.findall(normalized):
        if re.fullmatch(r"[\u4e00-\u9fff]+", piece):
            tokens.extend(token.strip() for token in jieba.lcut_for_search(piece))
        else:
            tokens.append(piece)
    tokens = [token for token in tokens if token]
    return tokens or [normalized.strip() or "empty"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build FAISS vector and BM25 indexes from report chunks."
    )
    parser.add_argument(
        "--chunks",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "chunks.jsonl",
    )
    parser.add_argument(
        "--index-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "index",
    )
    parser.add_argument("--model", default=os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL))
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    chunks_path = args.chunks.resolve()
    index_dir = args.index_dir.resolve()
    index_dir.mkdir(parents=True, exist_ok=True)
    chunks = load_chunks(chunks_path)
    chunks_checksum = sha256_file(chunks_path)

    embedding_path = index_dir / "embeddings.npy"
    embedding_meta_path = index_dir / "embedding_meta.json"
    reuse_embeddings = False
    if embedding_path.exists() and embedding_meta_path.exists():
        embedding_meta = json.loads(embedding_meta_path.read_text(encoding="utf-8"))
        reuse_embeddings = (
            embedding_meta.get("source_chunks_sha256") == chunks_checksum
            and embedding_meta.get("embedding_model") == args.model
        )

    if reuse_embeddings:
        print(f"Reusing embeddings from {embedding_path}")
        embeddings = np.load(embedding_path).astype(np.float32)
    else:
        print(f"Loading embedding model: {args.model}")
        model = SentenceTransformer(args.model, device="cpu")
        texts = [chunk["content"] for chunk in chunks]
        print(f"Embedding {len(texts):,} chunks on CPU...")
        embeddings = model.encode(
            texts,
            batch_size=args.batch_size,
            show_progress_bar=True,
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype(np.float32)
        np.save(embedding_path, embeddings)
        embedding_meta_path.write_text(
            json.dumps(
                {
                    "embedding_model": args.model,
                    "rows": len(embeddings),
                    "dimension": int(embeddings.shape[1]),
                    "source_chunks_sha256": chunks_checksum,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    dimension = int(embeddings.shape[1])
    vector_index = faiss.IndexFlatIP(dimension)
    vector_index.add(embeddings)
    np.save(
        index_dir / "vectors.faiss.npy",
        faiss.serialize_index(vector_index),
    )

    print("Building BM25 index...")
    tokenized_corpus = [tokenize(chunk["content"]) for chunk in chunks]
    bm25 = BM25Okapi(tokenized_corpus)
    with (index_dir / "bm25.pkl").open("wb") as handle:
        pickle.dump(bm25, handle, protocol=pickle.HIGHEST_PROTOCOL)

    (index_dir / "chunks.jsonl").write_text(
        chunks_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "embedding_model": args.model,
        "embedding_dimension": dimension,
        "chunks": len(chunks),
        "chunk_types": {
            "text": sum(chunk["chunk_type"] == "text" for chunk in chunks),
            "table": sum(chunk["chunk_type"] == "table" for chunk in chunks),
        },
        "companies": sorted({chunk["company"] for chunk in chunks}),
        "source_chunks_sha256": chunks_checksum,
        "vector_index": "FAISS IndexFlatIP with normalized embeddings",
        "keyword_index": "BM25Okapi over jieba search tokens",
    }
    (index_dir / "index_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
