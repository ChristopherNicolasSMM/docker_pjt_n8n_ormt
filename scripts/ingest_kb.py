#!/usr/bin/env python3
import os
import re
import json
import time
import hashlib
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct, VectorParams, Distance


# ----------------------------
# Helpers
# ----------------------------
FRONT_MATTER_RE = re.compile(r"^---\s*$", re.MULTILINE)

def words_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))

def sha1_12(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]

def parse_front_matter(md: str):
    """
    Parseia front matter simples do formato:

    ---
    key: "value"
    key2: 123
    ---
    body...

    Retorna (meta: dict, body: str)
    """
    lines = md.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, md

    # achar fim do front matter
    end_idx = None
    for i in range(1, min(len(lines), 200)):  # front matter não deve ser enorme
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}, md

    meta_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1:]).lstrip("\n")

    meta = {}
    for ln in meta_lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ":" not in ln:
            continue
        k, v = ln.split(":", 1)
        k = k.strip()
        v = v.strip()
        # Tentar json.loads (funciona bem pq seus strings estão em JSON "...")
        try:
            meta[k] = json.loads(v)
        except Exception:
            # fallback: remove aspas externas se houver
            meta[k] = v.strip('"').strip("'")

    return meta, body

def iter_chunk_files(knowledge_root: Path, glob_pattern: str):
    return sorted(knowledge_root.glob(glob_pattern))

def ensure_collection(client: QdrantClient, collection: str, vector_size: int, distance: str):
    existing = [c.name for c in client.get_collections().collections]
    if collection in existing:
        return

    dist = {
        "Cosine": Distance.COSINE,
        "Dot": Distance.DOT,
        "Euclid": Distance.EUCLID,
    }.get(distance, Distance.COSINE)

    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=vector_size, distance=dist),
    )


# ----------------------------
# Embedding (Ollama)
# ----------------------------
def embed_ollama(ollama_url: str, model: str, text: str, timeout: int = 120):
    r = requests.post(
        f"{ollama_url}/api/embeddings",
        json={"model": model, "prompt": text},
        timeout=timeout
    )
    r.raise_for_status()
    data = r.json()
    return data["embedding"]


# ----------------------------
# Main ingest pipeline
# ----------------------------
def main():
    parser = argparse.ArgumentParser(description="Ingest RAG chunks (knowledge/**/chunks/*.md) into Qdrant using Ollama embeddings.")
    parser.add_argument("--knowledge-root", default="knowledge", help="Pasta raiz de knowledge/ (default: knowledge)")
    parser.add_argument("--glob", default="**/chunks/*.md", help="Glob relativo ao knowledge-root (default: **/chunks/*.md)")
    parser.add_argument("--collection", default=os.getenv("QDRANT_COLLECTION", "runomante_kb"), help="Nome da coleção Qdrant")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"), help="URL do Qdrant")
    parser.add_argument("--ollama-url", default=os.getenv("OLLAMA_URL", "http://localhost:11434"), help="URL do Ollama")
    parser.add_argument("--embed-model", default=os.getenv("EMBED_MODEL", "nomic-embed-text"), help="Modelo de embeddings (Ollama)")
    parser.add_argument("--distance", default=os.getenv("QDRANT_DISTANCE", "Cosine"), choices=["Cosine", "Dot", "Euclid"], help="Distância vetorial")
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("BATCH", "200")), help="Tamanho do lote de upsert (100-500 recomendado)")
    parser.add_argument("--workers", type=int, default=int(os.getenv("WORKERS", "2")), help="Paralelismo para embeddings (2-4 recomendado p/ 8GB)")
    parser.add_argument("--timeout", type=int, default=int(os.getenv("EMBED_TIMEOUT", "120")), help="Timeout (s) do embedding")
    parser.add_argument("--dry-run", action="store_true", help="Não grava no Qdrant, só simula.")
    args = parser.parse_args()

    knowledge_root = Path(args.knowledge_root).resolve()
    if not knowledge_root.exists():
        raise SystemExit(f"❌ Pasta não encontrada: {knowledge_root}")

    files = list(iter_chunk_files(knowledge_root, args.glob))
    if not files:
        raise SystemExit(f"❌ Nenhum arquivo encontrado em {knowledge_root} com glob '{args.glob}'")

    print(f"📚 Knowledge root: {knowledge_root}")
    print(f"🔎 Encontrados: {len(files)} chunks (.md) via glob '{args.glob}'")
    print(f"🧠 Embeddings: {args.embed_model} @ {args.ollama_url}")
    print(f"🧱 Qdrant: {args.qdrant_url} | collection={args.collection} | distance={args.distance}")
    print(f"⚙️ batch={args.batch_size} | workers={args.workers} | dry_run={args.dry_run}")

    # Teste embedding para descobrir dimensão
    t_dim0 = time.time()
    test_vec = embed_ollama(args.ollama_url, args.embed_model, "teste", timeout=args.timeout)
    vector_size = len(test_vec)
    print(f"📐 Dimensão do embedding detectada: {vector_size} (em {time.time()-t_dim0:.2f}s)")

    # Qdrant client + ensure collection
    client = QdrantClient(url=args.qdrant_url)
    ensure_collection(client, args.collection, vector_size, args.distance)

    # Métricas
    t0 = time.time()
    total_words = 0
    total_bytes = 0
    total_points = 0
    total_docs = set()
    errors = 0

    # Buffer de pontos prontos p/ upsert
    batch_points = []

    def build_point(path: Path):
        """Lê um chunk .md, extrai meta+texto e retorna (PointStruct, stats_dict)."""
        raw = path.read_text(encoding="utf-8", errors="ignore")
        meta, body = parse_front_matter(raw)

        # doc_id: se tiver no front matter use, senão derive do diretório do livro
        doc_id = meta.get("doc_id")
        if not doc_id:
            # ex: knowledge/compendio_futhark_antigo/chunks/0001.md -> compendio_futhark_antigo
            parts = path.parts
            # pega o diretório imediatamente abaixo de knowledge/
            try:
                idx = parts.index(knowledge_root.name)
                doc_id = parts[idx + 1]
            except Exception:
                doc_id = path.parent.parent.name

        # texto efetivo para embeddings: body (sem front matter)
        text = body.strip()
        if not text:
            # evita inserir ponto vazio
            return None, {"doc_id": doc_id, "words": 0, "bytes": len(raw)}

        # id estável: preferir meta['id'], senão hash do path+conteúdo
        pid = meta.get("id")
        if not pid:
            pid = sha1_12(str(path) + "\n" + text[:2000])

        # metadados úteis no payload
        payload = {
            "text": text,
            "doc_id": doc_id,
            "source_path": str(path.relative_to(knowledge_root)),
            "chunk_file": path.name,
            "chunk_index": meta.get("chunk"),
            "chunks_total": meta.get("chunks_total"),
            "heading_path": meta.get("heading_path"),
            "title": meta.get("title"),
            "source": meta.get("source"),
            "generated_at": meta.get("generated_at"),
            "words": meta.get("words", words_count(text)),
        }

        # embedding
        vec = embed_ollama(args.ollama_url, args.embed_model, text, timeout=args.timeout)

        point = PointStruct(id=pid, vector=vec, payload=payload)
        stats = {"doc_id": doc_id, "words": payload["words"], "bytes": len(raw)}
        return point, stats

    def flush_batch():
        nonlocal batch_points, total_points
        if not batch_points:
            return
        if args.dry_run:
            total_points += len(batch_points)
            batch_points = []
            return
        client.upsert(collection_name=args.collection, points=batch_points)
        total_points += len(batch_points)
        batch_points = []

    # Paralelismo para embeddings (I/O-bound HTTP)
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futures = {ex.submit(build_point, p): p for p in files}

        for fut in as_completed(futures):
            path = futures[fut]
            try:
                result = fut.result()
            except Exception as e:
                errors += 1
                print(f"❌ ERRO em {path}: {e}")
                continue

            if result is None:
                continue

            point, st = result
            if point is None:
                continue

            total_docs.add(st["doc_id"])
            total_words += st["words"]
            total_bytes += st["bytes"]

            batch_points.append(point)

            if len(batch_points) >= args.batch_size:
                flush_batch()

        # flush final
        flush_batch()

    dt = time.time() - t0
    chunks_per_s = (total_points / dt) if dt > 0 else 0.0

    print("\n✅ INGEST CONCLUÍDO")
    print(f"- Coleção: {args.collection}")
    print(f"- Docs detectados: {len(total_docs)}")
    print(f"- Chunks inseridos (upsert): {total_points}")
    print(f"- Palavras totais (aprox): {total_words}")
    print(f"- Bytes lidos: {total_bytes}")
    print(f"- Erros: {errors}")
    print(f"- Tempo total: {dt:.1f}s")
    print(f"- Throughput: {chunks_per_s:.2f} chunks/s")

    # Dica rápida
    if args.workers > 4:
        print("\n⚠️ Dica: com 8GB RAM, workers>4 pode piorar (Ollama e swap).")


if __name__ == "__main__":
    main()
