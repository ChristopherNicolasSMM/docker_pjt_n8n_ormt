from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from flask import Flask, jsonify, request
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from ingest import IngestConfig, ingest_directory

# ----------------------------
# Config (env-driven)
# ----------------------------

APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "chunks")

CHUNKS_DIR = Path(os.getenv("CHUNKS_DIR", "./chunks"))

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
CHAT_MODEL = os.getenv("CHAT_MODEL", "llama3.1")

# Safety limits to avoid: "input length exceeds the context length" (embeddings)
EMBED_MAX_CHARS = int(os.getenv("EMBED_MAX_CHARS", "6000"))
EMBED_MAX_WORDS = int(os.getenv("EMBED_MAX_WORDS", "900")) if os.getenv("EMBED_MAX_WORDS", "").strip() else 900

DEFAULT_TOP_K = int(os.getenv("TOP_K", "6"))

# ----------------------------
# App + job store
# ----------------------------

app = Flask(__name__)

JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


def _qdrant() -> QdrantClient:
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)


def _ollama_embed(text: str) -> list[float]:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/embeddings"
    r = requests.post(url, json={"model": EMBED_MODEL, "prompt": text}, timeout=90)
    r.raise_for_status()
    data = r.json()
    emb = data.get("embedding")
    if not isinstance(emb, list) or not emb:
        raise RuntimeError(f"Unexpected embedding response: {data}")
    return emb


def _ollama_chat(prompt: str) -> str:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    r = requests.post(
        url,
        json={
            "model": CHAT_MODEL,
            "prompt": prompt,
            "stream": False,
            # You can tune these if needed:
            "options": {"temperature": 0.2},
        },
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()
    return data.get("response", "").strip()


def _make_ingest_cfg() -> IngestConfig:
    return IngestConfig(
        chunks_dir=CHUNKS_DIR,
        collection_name=QDRANT_COLLECTION,
        qdrant_host=QDRANT_HOST,
        qdrant_port=QDRANT_PORT,
        ollama_base_url=OLLAMA_BASE_URL,
        embed_model=EMBED_MODEL,
        embed_max_chars=EMBED_MAX_CHARS,
        embed_max_words=EMBED_MAX_WORDS,
    )


def _start_ingest_job(*, recreate: bool) -> str:
    job_id = str(uuid.uuid4())

    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "status": "running",
            "created_at": time.time(),
            "updated_at": time.time(),
            "progress": {"stage": "queued"},
            "result": None,
            "error": None,
        }

    def progress_cb(update: Dict[str, Any]) -> None:
        with JOBS_LOCK:
            JOBS[job_id]["progress"] = update
            JOBS[job_id]["updated_at"] = time.time()

    def worker() -> None:
        try:
            cfg = _make_ingest_cfg()
            result = ingest_directory(cfg, recreate_collection=recreate, progress_cb=progress_cb)
            with JOBS_LOCK:
                JOBS[job_id]["status"] = "done"
                JOBS[job_id]["result"] = result
                JOBS[job_id]["updated_at"] = time.time()
        except Exception as e:
            with JOBS_LOCK:
                JOBS[job_id]["status"] = "error"
                JOBS[job_id]["error"] = str(e)
                JOBS[job_id]["updated_at"] = time.time()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return job_id


# ----------------------------
# Routes
# ----------------------------


@app.get("/health")
def health():
    return jsonify(
        {
            "ok": True,
            "qdrant": {"host": QDRANT_HOST, "port": QDRANT_PORT, "collection": QDRANT_COLLECTION},
            "ollama": {"base_url": OLLAMA_BASE_URL, "embed_model": EMBED_MODEL, "chat_model": CHAT_MODEL},
            "chunks_dir": str(CHUNKS_DIR),
            "limits": {"embed_max_chars": EMBED_MAX_CHARS, "embed_max_words": EMBED_MAX_WORDS},
        }
    )


@app.post("/ingest")
def ingest_route():
    body = request.get_json(silent=True) or {}
    recreate = bool(body.get("recreate", False))
    job_id = _start_ingest_job(recreate=recreate)
    return jsonify({"ok": True, "job_id": job_id})


@app.get("/ingest/<job_id>")
def ingest_status(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "job_not_found"}), 404
    return jsonify({"ok": True, "job": job})


@app.get("/collections")
def collections():
    client = _qdrant()
    cols = [c.name for c in client.get_collections().collections]
    return jsonify({"ok": True, "collections": cols})


@app.post("/query")
def query():
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"ok": False, "error": "missing_question"}), 400

    top_k = int(body.get("top_k") or DEFAULT_TOP_K)

    # Embed the question
    qvec = _ollama_embed(question)

    # Search Qdrant
    client = _qdrant()
    hits = client.search(
        collection_name=QDRANT_COLLECTION,
        query_vector=qvec,
        limit=top_k,
        with_payload=True,
    )

    contexts = []
    sources = []
    for h in hits:
        payload = h.payload or {}
        txt = (payload.get("text") or "").strip()
        src = payload.get("filename") or payload.get("source") or ""
        if txt:
            contexts.append(txt)
        sources.append({"source": src, "score": float(h.score)})

    context_block = "\n\n---\n\n".join(contexts)

    # Very conservative prompt to keep it stable.
    prompt = (
        "Você é um assistente. Use SOMENTE o contexto abaixo para responder. "
        "Se o contexto não contiver a resposta, diga que não encontrou no material.\n\n"
        f"[CONTEXTO]\n{context_block}\n\n"
        f"[PERGUNTA]\n{question}\n\n"
        "[RESPOSTA]\n"
    )

    answer = _ollama_chat(prompt)

    return jsonify({"ok": True, "answer": answer, "sources": sources})


@app.get("/chunks")
def list_chunks():
    if not CHUNKS_DIR.exists():
        return jsonify({"ok": True, "chunks": [], "warning": "chunks_dir_not_found"})
    files = sorted([p.name for p in CHUNKS_DIR.glob("*.md") if p.is_file()])
    return jsonify({"ok": True, "chunks": files, "count": len(files)})


if __name__ == "__main__":
    app.run(host=APP_HOST, port=APP_PORT)
