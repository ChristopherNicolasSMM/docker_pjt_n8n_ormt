\
import os
import re
import json
import time
import hashlib
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, abort, Response

from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct, VectorParams, Distance, Filter, FieldCondition, MatchValue


KNOWLEDGE_ROOT = Path(os.getenv("KNOWLEDGE_ROOT", "/app/knowledge")).resolve()

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "runomante_kb")
QDRANT_DISTANCE = os.getenv("QDRANT_DISTANCE", "Cosine")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
CHAT_MODEL_DEFAULT = os.getenv("CHAT_MODEL", "llama3.2:3b")

BASIC_AUTH_USER = os.getenv("BASIC_AUTH_USER", "").strip()
BASIC_AUTH_PASSWORD = os.getenv("BASIC_AUTH_PASSWORD", "").strip()

ALLOWED_UPLOAD_EXT = {".md", ".txt", ".pdf", ".docx"}
DEFAULT_MAX_WORDS = int(os.getenv("CHUNK_MAX_WORDS", "900"))
DEFAULT_OVERLAP_WORDS = int(os.getenv("CHUNK_OVERLAP_WORDS", "120"))

app = Flask(
    __name__,
    template_folder="../templates",
    static_folder="../static"
)

app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me-in-env")


def _auth_required() -> bool:
    return bool(BASIC_AUTH_USER and BASIC_AUTH_PASSWORD)

def _check_basic_auth():
    if not _auth_required():
        return

    auth = request.authorization
    if not auth or auth.username != BASIC_AUTH_USER or auth.password != BASIC_AUTH_PASSWORD:
        return Response(
            "Unauthorized",
            401,
            {"WWW-Authenticate": 'Basic realm="Login Required"'}
        )

@app.before_request
def _before():
    if request.path.startswith("/static"):
        return
    _check_basic_auth()


def safe_join(base: Path, rel: str) -> Path:
    rel = (rel or "").lstrip("/").replace("\\", "/")
    p = (base / rel).resolve()
    if not str(p).startswith(str(base)):
        raise ValueError("Path traversal detectado")
    return p

def sizeof_fmt(num: int) -> str:
    for unit in ["B","KB","MB","GB","TB"]:
        if num < 1024.0:
            return f"{num:.1f}{unit}"
        num /= 1024.0
    return f"{num:.1f}PB"

def sha1_12(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]

def words_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))

def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "book"


def parse_front_matter(md: str) -> Tuple[dict, str]:
    lines = md.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, md
    end_idx = None
    for i in range(1, min(len(lines), 250)):
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
        if not ln or ln.startswith("#") or ":" not in ln:
            continue
        k, v = ln.split(":", 1)
        k = k.strip()
        v = v.strip()
        try:
            meta[k] = json.loads(v)
        except Exception:
            meta[k] = v.strip('"').strip("'")
    return meta, body


def ollama_embeddings(prompt: str, timeout: int = 120) -> List[float]:
    r = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": prompt},
        timeout=timeout
    )
    r.raise_for_status()
    return r.json()["embedding"]

def ollama_generate(prompt: str, model: str, timeout: int = 300) -> str:
    r = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=timeout
    )
    r.raise_for_status()
    return r.json().get("response", "")


def qdrant_client() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL)

def ensure_collection(client: QdrantClient, vector_size: int):
    existing = [c.name for c in client.get_collections().collections]
    if QDRANT_COLLECTION in existing:
        return

    dist = {
        "Cosine": Distance.COSINE,
        "Dot": Distance.DOT,
        "Euclid": Distance.EUCLID,
    }.get(QDRANT_DISTANCE, Distance.COSINE)

    client.create_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config=VectorParams(size=vector_size, distance=dist),
    )


def docx_to_markdown(path: Path) -> str:
    from docx import Document
    doc = Document(str(path))
    out = []
    for p in doc.paragraphs:
        text = p.text.replace("\u00A0", " ").rstrip()
        if not text.strip():
            out.append("")
            continue
        out.append(text)
        out.append("")
    return "\n".join(out).strip() + "\n"

def pdf_to_text_markdown(path: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    out = []
    for i, page in enumerate(reader.pages, start=1):
        txt = (page.extract_text() or "").strip()
        if not txt:
            continue
        out.append(f"## Página {i}")
        out.append("")
        out.append(txt)
        out.append("")
    return "\n".join(out).strip() + "\n"


def chunk_text(md_text: str, max_words: int, overlap_words: int) -> List[str]:
    words = re.findall(r"\S+|\n", md_text)
    flat = list(words)

    chunks = []
    i = 0
    while i < len(flat):
        wcount = 0
        j = i
        buf = []
        while j < len(flat) and wcount < max_words:
            tok = flat[j]
            buf.append(tok)
            if tok != "\n":
                wcount += 1
            j += 1

        chunk = " ".join([t if t != "\n" else "\n" for t in buf])
        chunk = re.sub(r"[ \t]+\n", "\n", chunk)
        chunk = re.sub(r"\n{3,}", "\n\n", chunk).strip() + "\n"
        if chunk.strip():
            chunks.append(chunk)

        if j >= len(flat):
            break

        back = 0
        k = j - 1
        while k > i and back < overlap_words:
            if flat[k] != "\n":
                back += 1
            k -= 1
        i = max(i + 1, k)

    return chunks


@dataclass
class Item:
    name: str
    rel: str
    is_dir: bool
    size_h: str

@dataclass
class Status:
    ollama_ok: bool
    qdrant_ok: bool
    collection: str
    embed_dim: Optional[int]
    embed_model: str
    chat_model: str

@dataclass
class Context:
    score: float
    doc_id: str
    source_path: str
    text: str


@app.get("/")
def dashboard():
    KNOWLEDGE_ROOT.mkdir(parents=True, exist_ok=True)

    st = Status(
        ollama_ok=False,
        qdrant_ok=False,
        collection=QDRANT_COLLECTION,
        embed_dim=None,
        embed_model=EMBED_MODEL,
        chat_model=CHAT_MODEL_DEFAULT
    )

    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        st.ollama_ok = (r.status_code == 200)
        if st.ollama_ok:
            vec = ollama_embeddings("teste", timeout=15)
            st.embed_dim = len(vec)
    except Exception:
        pass

    cols = []
    try:
        c = qdrant_client()
        cols = [x.name for x in c.get_collections().collections]
        st.qdrant_ok = True
    except Exception:
        st.qdrant_ok = False

    return render_template("dashboard.html", title="Dashboard", knowledge_root=str(KNOWLEDGE_ROOT), status=st, collections=cols)


@app.get("/browse")
def browse():
    KNOWLEDGE_ROOT.mkdir(parents=True, exist_ok=True)
    rel = request.args.get("path", "") or ""
    try:
        p = safe_join(KNOWLEDGE_ROOT, rel)
    except Exception:
        flash("Caminho inválido.", "danger")
        return redirect(url_for("browse"))

    if not p.exists():
        flash("Diretório não existe.", "warning")
        return redirect(url_for("browse"))

    if not p.is_dir():
        return redirect(url_for("view_file", path=rel))

    items = []
    for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        try:
            size = 0 if child.is_dir() else child.stat().st_size
        except Exception:
            size = 0
        items.append(Item(
            name=child.name,
            rel=str(child.relative_to(KNOWLEDGE_ROOT)),
            is_dir=child.is_dir(),
            size_h="-" if child.is_dir() else sizeof_fmt(size),
        ))

    parent_path = str(p.parent.relative_to(KNOWLEDGE_ROOT)) if p != KNOWLEDGE_ROOT else ""
    return render_template(
        "browse.html",
        title="Arquivos",
        knowledge_root=str(KNOWLEDGE_ROOT),
        rel_path=str(p.relative_to(KNOWLEDGE_ROOT)) if p != KNOWLEDGE_ROOT else "",
        parent_path=parent_path,
        items=items
    )


@app.post("/create-folder")
def create_folder():
    base = request.form.get("base", "") or ""
    name = request.form.get("name", "") or ""
    name = name.strip().replace("\\", "/").strip("/")
    if not name:
        flash("Nome de pasta inválido.", "danger")
        return redirect(url_for("browse", path=base))
    try:
        target = safe_join(KNOWLEDGE_ROOT, f"{base}/{name}".strip("/"))
        target.mkdir(parents=True, exist_ok=False)
        flash(f"Pasta criada: {target.relative_to(KNOWLEDGE_ROOT)}", "success")
    except FileExistsError:
        flash("Pasta já existe.", "warning")
    except Exception as e:
        flash(f"Erro ao criar pasta: {e}", "danger")
    return redirect(url_for("browse", path=base))


@app.post("/upload")
def upload_file():
    base = request.form.get("base", "") or ""
    f = request.files.get("file")
    if not f or not f.filename:
        flash("Selecione um arquivo.", "danger")
        return redirect(url_for("browse", path=base))

    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXT:
        flash(f"Extensão não permitida: {ext}", "danger")
        return redirect(url_for("browse", path=base))

    try:
        dest_dir = safe_join(KNOWLEDGE_ROOT, base)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / Path(f.filename).name
        f.save(dest)
        flash(f"Upload ok: {dest.relative_to(KNOWLEDGE_ROOT)}", "success")
    except Exception as e:
        flash(f"Erro no upload: {e}", "danger")

    return redirect(url_for("browse", path=base))


@app.post("/delete")
def delete_path():
    rel = request.form.get("path", "") or ""
    try:
        p = safe_join(KNOWLEDGE_ROOT, rel)
        if p.is_dir():
            for sub in sorted(p.rglob("*"), reverse=True):
                if sub.is_file():
                    sub.unlink(missing_ok=True)
                else:
                    sub.rmdir()
            p.rmdir()
        else:
            p.unlink(missing_ok=True)
        flash(f"Removido: {rel}", "success")
    except Exception as e:
        flash(f"Erro ao remover: {e}", "danger")
    parent = str(Path(rel).parent) if "/" in rel else ""
    return redirect(url_for("browse", path=parent))


@app.get("/view")
def view_file():
    rel = request.args.get("path", "") or ""
    try:
        p = safe_join(KNOWLEDGE_ROOT, rel)
        if not p.exists() or not p.is_file():
            flash("Arquivo não encontrado.", "warning")
            return redirect(url_for("browse"))
        content = p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        flash(f"Erro ao abrir: {e}", "danger")
        return redirect(url_for("browse"))

    parent_path = str(Path(rel).parent) if "/" in rel else ""
    return render_template("view_file.html", title="Ver arquivo", knowledge_root=str(KNOWLEDGE_ROOT), rel_path=rel, parent_path=parent_path, content=content)


@app.get("/download")
def download_file():
    rel = request.args.get("path", "") or ""
    try:
        p = safe_join(KNOWLEDGE_ROOT, rel)
        if not p.exists() or not p.is_file():
            abort(404)
        return send_file(p, as_attachment=True, download_name=p.name)
    except Exception:
        abort(404)


@app.get("/convert")
def convert_page():
    src = request.args.get("src", "")
    return render_template("convert.html", title="Converter/Chunk", knowledge_root=str(KNOWLEDGE_ROOT), src=src)

@app.post("/convert")
def convert_run():
    src = (request.form.get("src", "") or "").strip()
    book_id = slugify(request.form.get("book_id", "") or "")
    max_words = int(request.form.get("max_words") or DEFAULT_MAX_WORDS)
    overlap_words = int(request.form.get("overlap_words") or DEFAULT_OVERLAP_WORDS)

    if not src or not book_id:
        flash("src e book_id são obrigatórios.", "danger")
        return redirect(url_for("convert_page"))

    try:
        src_path = safe_join(KNOWLEDGE_ROOT, src)
        if not src_path.exists() or not src_path.is_file():
            flash("Arquivo de origem não encontrado em knowledge/.", "danger")
            return redirect(url_for("convert_page", src=src))
    except Exception as e:
        flash(f"Caminho inválido: {e}", "danger")
        return redirect(url_for("convert_page", src=src))

    ext = src_path.suffix.lower()
    try:
        if ext == ".docx":
            md = docx_to_markdown(src_path)
        elif ext == ".pdf":
            md = pdf_to_text_markdown(src_path)
        elif ext in (".md", ".txt"):
            md = src_path.read_text(encoding="utf-8", errors="ignore")
        else:
            flash("Extensão não suportada para conversão.", "danger")
            return redirect(url_for("convert_page", src=src))
    except Exception as e:
        flash(f"Falha ao converter: {e}", "danger")
        return redirect(url_for("convert_page", src=src))

    book_dir = KNOWLEDGE_ROOT / book_id
    chunks_dir = book_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    (book_dir / "full.md").write_text(md, encoding="utf-8")
    chunks = chunk_text(md, max_words=max_words, overlap_words=overlap_words)

    gen_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    index_lines = [
        f"# INDEX — {book_id}",
        "",
        f"- source: {src}",
        f"- generated_at: {gen_at}",
        f"- chunks_total: {len(chunks)}",
        f"- max_words: {max_words}",
        f"- overlap_words: {overlap_words}",
        "",
        "## Chunks",
        "",
    ]

    for i, ch in enumerate(chunks, start=1):
        cid = sha1_12(f"{book_id}:{i}:{ch[:500]}")
        fm = {
            "id": cid,
            "doc_id": book_id,
            "source": src,
            "chunk": i,
            "chunks_total": len(chunks),
            "words": words_count(ch),
            "generated_at": gen_at
        }
        yaml = "---\n" + "\n".join([f"{k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, str) else v}" for k, v in fm.items()]) + "\n---\n\n"
        fn = f"{i:04d}.md"
        (chunks_dir / fn).write_text(yaml + ch, encoding="utf-8")
        index_lines.append(f"- {i:04d}: chunks/{fn}")

    (book_dir / "INDEX.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")

    flash(f"Gerado: knowledge/{book_id}/ (chunks={len(chunks)})", "success")
    return redirect(url_for("browse", path=book_id))


@app.get("/ingest")
def ingest_page():
    return render_template("ingest.html", title="Indexar", knowledge_root=str(KNOWLEDGE_ROOT), result=None)

@app.post("/ingest")
def ingest_run():
    book_id = slugify(request.form.get("book_id", "") or "")
    batch_size = int(request.form.get("batch_size") or 200)
    workers = int(request.form.get("workers") or 2)

    if not book_id:
        flash("book_id é obrigatório.", "danger")
        return redirect(url_for("ingest_page"))

    chunks_dir = KNOWLEDGE_ROOT / book_id / "chunks"
    if not chunks_dir.exists():
        flash(f"chunks não encontrado: knowledge/{book_id}/chunks", "danger")
        return redirect(url_for("ingest_page"))

    files = sorted(chunks_dir.glob("*.md"))
    if not files:
        flash("Nenhum chunk .md encontrado.", "warning")
        return redirect(url_for("ingest_page"))

    try:
        vec = ollama_embeddings("teste", timeout=15)
        dim = len(vec)
    except Exception as e:
        flash(f"Ollama embedding falhou: {e}", "danger")
        return redirect(url_for("ingest_page"))

    try:
        qc = qdrant_client()
        ensure_collection(qc, dim)
    except Exception as e:
        flash(f"Qdrant falhou: {e}", "danger")
        return redirect(url_for("ingest_page"))

    t0 = time.time()
    inserted = 0
    errors = 0
    points = []

    def build_point(path: Path):
        raw = path.read_text(encoding="utf-8", errors="ignore")
        meta, body = parse_front_matter(raw)
        text = body.strip()
        if not text:
            return None
        pid = meta.get("id") or sha1_12(str(path) + text[:300])
        payload = {
            "text": text,
            "doc_id": book_id,
            "source_path": str(path.relative_to(KNOWLEDGE_ROOT)),
            "chunk_file": path.name,
            "chunk_index": meta.get("chunk"),
            "chunks_total": meta.get("chunks_total"),
            "heading_path": meta.get("heading_path"),
            "title": meta.get("title"),
            "source": meta.get("source"),
            "generated_at": meta.get("generated_at"),
            "words": meta.get("words", words_count(text)),
        }
        v = ollama_embeddings(text, timeout=120)
        return PointStruct(id=pid, vector=v, payload=payload)

    def flush():
        nonlocal inserted, points
        if not points:
            return
        qc.upsert(collection_name=QDRANT_COLLECTION, points=points)
        inserted += len(points)
        points = []

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futures = {ex.submit(build_point, p): p for p in files}
        for fut in as_completed(futures):
            try:
                pt = fut.result()
                if pt is None:
                    continue
                points.append(pt)
                if len(points) >= batch_size:
                    flush()
            except Exception:
                errors += 1
        flush()

    dt = time.time() - t0
    result = {
        "book_id": book_id,
        "files": len(files),
        "inserted": inserted,
        "errors": errors,
        "seconds": round(dt, 2),
        "chunks_per_sec": round(inserted / dt, 3) if dt > 0 else 0,
        "collection": QDRANT_COLLECTION,
    }

    flash(f"Indexação concluída: inserted={inserted} errors={errors} time={dt:.1f}s", "success")
    return render_template("ingest.html", title="Indexar", knowledge_root=str(KNOWLEDGE_ROOT), result=json.dumps(result, ensure_ascii=False, indent=2))


@app.get("/ask")
def ask_page():
    return render_template(
        "ask.html",
        title="Testar RAG",
        knowledge_root=str(KNOWLEDGE_ROOT),
        answer=None,
        contexts=[],
        form={"question": "", "doc_id": "", "top_k": 6, "chat_model": CHAT_MODEL_DEFAULT},
        default_chat_model=CHAT_MODEL_DEFAULT
    )

@app.post("/ask")
def ask_run():
    question = (request.form.get("question", "") or "").strip()
    doc_id = (request.form.get("doc_id", "") or "").strip()
    top_k = int(request.form.get("top_k") or 6)
    chat_model = (request.form.get("chat_model", "") or CHAT_MODEL_DEFAULT).strip()

    if not question:
        flash("Pergunta é obrigatória.", "danger")
        return redirect(url_for("ask_page"))

    try:
        qvec = ollama_embeddings(question, timeout=30)
    except Exception as e:
        flash(f"Falha no embedding: {e}", "danger")
        return redirect(url_for("ask_page"))

    try:
        qc = qdrant_client()
        flt = None
        if doc_id:
            flt = Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))])
        hits = qc.search(
            collection_name=QDRANT_COLLECTION,
            query_vector=qvec,
            limit=max(1, min(top_k, 20)),
            with_payload=True,
            query_filter=flt
        )
    except Exception as e:
        flash(f"Falha na busca Qdrant: {e}", "danger")
        return redirect(url_for("ask_page"))

    contexts: List[Context] = []
    ctx_texts = []
    for h in hits:
        payload = h.payload or {}
        txt = (payload.get("text") or "").strip()
        if not txt:
            continue
        contexts.append(Context(
            score=float(h.score),
            doc_id=str(payload.get("doc_id", "")),
            source_path=str(payload.get("source_path", "")),
            text=txt[:2000]
        ))
        ctx_texts.append(txt)

    context_block = "\n\n---\n\n".join(ctx_texts[:top_k])
    final_prompt = (
        "Você é um assistente. Responda em PT-BR.\n"
        "Use APENAS o CONTEXTO abaixo. Se não houver informação suficiente no contexto, diga claramente que não encontrou nos dados.\n\n"
        f"CONTEXTO:\n{context_block}\n\n"
        f"PERGUNTA:\n{question}\n\n"
        "RESPOSTA:"
    )

    try:
        answer = ollama_generate(final_prompt, model=chat_model, timeout=300)
    except Exception as e:
        flash(f"Falha ao gerar resposta: {e}", "danger")
        return redirect(url_for("ask_page"))

    return render_template(
        "ask.html",
        title="Testar RAG",
        knowledge_root=str(KNOWLEDGE_ROOT),
        answer=answer,
        contexts=contexts,
        form={"question": question, "doc_id": doc_id, "top_k": top_k, "chat_model": chat_model},
        default_chat_model=CHAT_MODEL_DEFAULT
    )


@app.get("/health")
def health():
    return {"status": "ok", "knowledge_root": str(KNOWLEDGE_ROOT)}
