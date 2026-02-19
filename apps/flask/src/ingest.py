"""Ingest markdown chunks into Qdrant.

Fixes common Qdrant 400 error:
- Point IDs MUST be unsigned integers or UUIDs.
  If you send a hex digest (e.g. "328340af54f6") Qdrant rejects it.
  This module always uses deterministic UUIDv5 IDs.

Usage (CLI):
  python ingest.py --book-id my_book --chunks-dir ./chunks --qdrant-url http://localhost:6333 --collection chunks

Or from app.py:
  from ingest import ingest_directory
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from uuid import UUID, uuid5, NAMESPACE_URL

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from embedding_utils import embed_texts, EmbeddingConfig


# ----------------------------
# IDs
# ----------------------------

def make_point_id(*parts: str) -> str:
    """Deterministic UUID point id from arbitrary parts."""
    key = ":".join(p.strip() for p in parts if p is not None)
    return str(uuid5(NAMESPACE_URL, key))


def coerce_point_id(value: Any, namespace: str = "default") -> str:
    """Coerce user-provided IDs into a valid Qdrant point ID (UUID string)."""
    if value is None:
        return ""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, int):
        # Convert int to UUID deterministically so the ID space is consistent.
        return make_point_id(namespace, str(value))
    s = str(value).strip()
    if not s:
        return ""
    # Already UUID?
    try:
        return str(UUID(s))
    except Exception:
        pass
    # Any other string (hex digests, docker hostname, filenames, etc.) -> UUIDv5
    return make_point_id(namespace, s)


# ----------------------------
# Config
# ----------------------------

@dataclass
class IngestResult:
    book_id: str
    total: int
    processed: int
    inserted: int
    errors: int
    status: str
    message: str


def _read_text_file(fp: Path) -> str:
    return fp.read_text(encoding="utf-8", errors="replace")


def _iter_md_files(chunks_dir: Path) -> List[Path]:
    files = sorted([p for p in chunks_dir.rglob("*.md") if p.is_file()])
    return files


def _ensure_collection(
    client: QdrantClient,
    collection: str,
    vector_size: int,
    distance: qmodels.Distance = qmodels.Distance.COSINE,
) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if collection in existing:
        return
    client.create_collection(
        collection_name=collection,
        vectors_config=qmodels.VectorParams(size=vector_size, distance=distance),
    )


def ingest_directory(
    *,
    book_id: str,
    chunks_dir: str | Path,
    qdrant_url: str,
    collection: str,
    embedding: EmbeddingConfig,
    batch_size: int = 64,
    extra_payload: Optional[Dict[str, Any]] = None,
) -> IngestResult:
    """Read *.md files from chunks_dir, embed, and upsert into Qdrant."""

    chunks_dir = Path(chunks_dir)
    files = _iter_md_files(chunks_dir)

    client = QdrantClient(url=qdrant_url)

    # We need vector size; compute one sample embedding.
    sample_vec = embed_texts(["ping"], embedding)[0]
    _ensure_collection(client, collection, vector_size=len(sample_vec))

    processed = 0
    inserted = 0
    errors = 0

    extra_payload = extra_payload or {}

    for i in range(0, len(files), batch_size):
        batch_files = files[i : i + batch_size]
        texts: List[str] = []
        metas: List[Dict[str, Any]] = []

        for fp in batch_files:
            try:
                text = _read_text_file(fp)
                # Minimal skip: ignore empty/whitespace-only
                if not text.strip():
                    continue
                texts.append(text)
                metas.append(
                    {
                        "book_id": book_id,
                        "source": str(fp.relative_to(chunks_dir)),
                        "filename": fp.name,
                        **extra_payload,
                    }
                )
            except Exception as e:
                errors += 1

        if not texts:
            processed += len(batch_files)
            continue

        try:
            vectors = embed_texts(texts, embedding)

            points: List[qmodels.PointStruct] = []
            for text, vec, meta, fp in zip(texts, vectors, metas, batch_files):
                # Deterministic ID per (book_id + relative path)
                pid = make_point_id(book_id, str(meta.get("source")))

                payload = {
                    **meta,
                    "text": text,
                }

                points.append(qmodels.PointStruct(id=pid, vector=vec, payload=payload))

            client.upsert(collection_name=collection, points=points)
            inserted += len(points)
        except Exception as e:
            errors += len(batch_files)
            return IngestResult(
                book_id=book_id,
                total=len(files),
                processed=processed + len(batch_files),
                inserted=inserted,
                errors=errors,
                status="error",
                message=f"Falha no ingest: {e}",
            )

        processed += len(batch_files)

    return IngestResult(
        book_id=book_id,
        total=len(files),
        processed=processed,
        inserted=inserted,
        errors=errors,
        status="ok" if errors == 0 else "partial",
        message="Ingest concluído" if errors == 0 else "Ingest concluído com erros",
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book-id", required=True)
    ap.add_argument("--chunks-dir", required=True)
    ap.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    ap.add_argument("--collection", default=os.getenv("QDRANT_COLLECTION", "chunks"))

    ap.add_argument("--provider", default=os.getenv("EMBED_PROVIDER", "openai"))
    ap.add_argument("--model", default=os.getenv("EMBED_MODEL", "text-embedding-3-small"))
    ap.add_argument("--dim", type=int, default=int(os.getenv("EMBED_DIM", "1536")))
    ap.add_argument("--batch-size", type=int, default=int(os.getenv("INGEST_BATCH", "64")))

    args = ap.parse_args()

    emb = EmbeddingConfig(provider=args.provider, model=args.model, dim=args.dim)

    res = ingest_directory(
        book_id=args.book_id,
        chunks_dir=args.chunks_dir,
        qdrant_url=args.qdrant_url,
        collection=args.collection,
        embedding=emb,
        batch_size=args.batch_size,
    )
    print(json.dumps(res.__dict__, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
