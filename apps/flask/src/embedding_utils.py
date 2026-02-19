"""Embedding + chunk utilities.

This file centralizes:
- Embedding calls (OpenAI or Ollama) with a simple interface.
- Light-weight text splitting helpers for markdown ingestion.

Why:
- Qdrant ingestion should be deterministic and robust.
- Different environments may use different embedding backends.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional

import requests


# ----------------------------
# Embeddings
# ----------------------------

@dataclass
class EmbeddingConfig:
    provider: str = "ollama"  # "ollama" | "openai"
    model: str = "nomic-embed-text"  # or "text-embedding-3-small"
    dim: Optional[int] = None  # optional validation

    # Ollama
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # OpenAI
    openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")


def _embed_ollama(texts: List[str], cfg: EmbeddingConfig) -> List[List[float]]:
    # Ollama supports /api/embeddings (single prompt per request). We'll loop.
    out: List[List[float]] = []
    url = cfg.ollama_base_url.rstrip("/") + "/api/embeddings"
    for t in texts:
        r = requests.post(url, json={"model": cfg.model, "prompt": t}, timeout=120)
        r.raise_for_status()
        data = r.json()
        vec = data.get("embedding")
        if not isinstance(vec, list):
            raise RuntimeError(f"Ollama embedding response missing 'embedding': {data}")
        out.append(vec)
    return out


def _embed_openai(texts: List[str], cfg: EmbeddingConfig) -> List[List[float]]:
    try:
        from openai import OpenAI
    except Exception as e:
        raise RuntimeError(
            "Provider=openai selected but the 'openai' package is not available. "
            "Install it (pip install openai) or switch to provider=ollama."
        ) from e

    if not cfg.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set for provider=openai")

    client = OpenAI(api_key=cfg.openai_api_key)
    resp = client.embeddings.create(model=cfg.model, input=texts)
    return [d.embedding for d in resp.data]


def embed_texts(texts: List[str], cfg: EmbeddingConfig) -> List[List[float]]:
    if not texts:
        return []

    provider = (cfg.provider or "").lower().strip()
    if provider in {"ollama", "local", "llama"}:
        vecs = _embed_ollama(texts, cfg)
    elif provider in {"openai"}:
        vecs = _embed_openai(texts, cfg)
    else:
        raise ValueError(f"Unknown embedding provider: {cfg.provider}")

    if cfg.dim is not None:
        for v in vecs:
            if len(v) != cfg.dim:
                raise RuntimeError(f"Embedding dim mismatch: expected {cfg.dim}, got {len(v)}")

    return vecs


# ----------------------------
# Chunking helpers (optional)
# ----------------------------

def estimate_tokens(text: str) -> int:
    """Fast heuristic token estimate (works OK for Latin scripts).
    Use only for rough limiting; real tokenization depends on the model.
    """
    # ~4 chars/token is a common rough heuristic.
    return max(1, len(text) // 4)


def split_by_max_chars(text: str, max_chars: int, overlap_chars: int = 200) -> List[str]:
    """Split text into chunks of <= max_chars, with overlap."""
    text = text or ""
    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        chunk = text[start:end]
        chunks.append(chunk)
        if end == len(text):
            break
        start = max(0, end - overlap_chars)
    return chunks


def split_markdown_semantic(text: str, max_chars: int = 6000, overlap_chars: int = 250) -> List[str]:
    """A simple semantic-ish splitter for markdown.

    Strategy:
    - Prefer splitting on headings or blank lines when possible.
    - Fall back to hard splits by characters.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # Split on headings first
    parts = re.split(r"(?m)^(?=#+\s)", text)
    # Re-assemble into <= max_chars
    out: List[str] = []
    buf = ""

    def flush():
        nonlocal buf
        if buf.strip():
            out.extend(split_by_max_chars(buf.strip(), max_chars=max_chars, overlap_chars=overlap_chars))
        buf = ""

    for part in parts:
        if not part.strip():
            continue
        if len(buf) + len(part) + 1 <= max_chars:
            buf = (buf + "\n" + part).strip() if buf else part
        else:
            flush()
            buf = part

    flush()
    return out
