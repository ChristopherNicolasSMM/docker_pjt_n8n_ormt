## Manual do Dashboard (Flask — Knowledge Console)

Fase: 1 | Risco: Baixo
Pré-requisitos: containers `srv-flask`, `srv-qdrant`, `srv-ollama` rodando (`docker compose ps`)

---

### O que é

O **Dashboard** é a tela inicial do seu **Knowledge Console**. Ele mostra:

* se **Ollama** está acessível
* se **Qdrant** está acessível
* qual **coleção** está configurada
* qual **modelo de embedding** e **chat** estão configurados
* (opcional) quais **coleções existem** no Qdrant

Acesse:

* `http://localhost:8000/`

---

## 1) Bloco “Status”

Você vai ver:

### 🧠 Ollama: OK / OFF

* **OK**: o Flask conseguiu chamar a API do Ollama
* **OFF**: não conseguiu (container parado, URL errada, rede, etc.)

**Verificação rápida:**

```bash
docker logs -n 80 srv-ollama
docker exec -it srv-ollama ollama list
```

### 📐 Dim (detectada)

É o tamanho do vetor gerado pelo seu modelo de embedding (ex.: 768, 1024, 1536…).

* Se aparecer um número → embeddings funcionando
* Se aparecer “-” → o Flask não conseguiu gerar embedding (Ollama OFF ou modelo faltando)

**Dica:** a dimensão **não é “texto”**, ela vem do modelo de embedding.
Ex.: `nomic-embed-text` costuma retornar um vetor fixo (depende do modelo).

### 🧱 Qdrant: OK / OFF

* **OK**: o Flask conectou no Qdrant
* **OFF**: Qdrant parado ou URL errada

**Verificação rápida:**

```bash
docker logs -n 80 srv-qdrant
curl -s http://localhost:6333/collections | head
```

### 📦 Coleção

Nome da coleção do Qdrant que o Flask vai usar para salvar/buscar embeddings.
Vem do `.env`:

* `QDRANT_COLLECTION=runomante_kb` (exemplo)

Se mudar esse valor, você cria/usa outra base separada.

### 🧩 Modelo Embedding

Modelo usado para transformar texto em vetor (embedding).
Exemplo:

* `nomic-embed-text`

Esse modelo **precisa estar baixado no Ollama**:

```bash
docker exec -it srv-ollama ollama pull nomic-embed-text
```

### 💬 Modelo Chat

Modelo usado para gerar resposta final (LLM).
Exemplo:

* `llama3.2:3b`

Baixar:

```bash
docker exec -it srv-ollama ollama pull llama3.2:3b
```

---

## 2) Bloco “Atalhos”

Esses botões são o fluxo operacional do seu RAG:

### 📁 Gerenciar arquivos em knowledge/

Vai para `/browse`
Use para:

* navegar em pastas
* criar pastas
* upload de arquivos
* abrir arquivos `.md` e `.txt`
* baixar arquivos
* excluir arquivos/pastas

### 🧾 Converter DOCX/PDF → Markdown + Chunks

Vai para `/convert`
Use quando você subir:

* `.docx` (Word)
* `.pdf`
* `.txt` ou `.md`

Ele cria:

* `knowledge/<book_id>/full.md`
* `knowledge/<book_id>/chunks/0001.md ...`
* `knowledge/<book_id>/INDEX.md` (**não indexa**)

### 🚀 Indexar chunks no Qdrant

Vai para `/ingest`
Envia para o Qdrant **somente**:

* `knowledge/<book_id>/chunks/*.md`

Com:

* batch upsert
* paralelismo (workers)
* métricas de performance (chunks/sec)

### 🔎 Perguntar (RAG)

Vai para `/ask`
Fluxo:

1. faz embedding da pergunta
2. busca top_k chunks no Qdrant
3. monta prompt com contexto
4. gera resposta via Ollama
5. mostra resposta + “contextos recuperados” (com score e origem)

---

## 3) Bloco “Coleções (Qdrant)”

Lista as coleções existentes no Qdrant.
Útil para verificar:

* se sua coleção foi criada
* se você está usando o nome certo

---

# Fluxo recomendado (checklist rápido)

1. `/browse` → criar pasta `compendio_futhark_antigo`
2. upload do `.docx` ou `.pdf`
3. `/convert` → gerar chunks
4. `/ingest` → indexar
5. `/ask` → perguntar e validar

---

## Troubleshooting rápido

### “Ollama OFF”

* container não subiu
* `OLLAMA_URL` errado
* modelo de embedding não baixado

### “Qdrant OFF”

* container `srv-qdrant` não subiu
* `QDRANT_URL` errado
* porta/volume travado

### Resposta “não encontrei nos dados”

* você não indexou (`/ingest`)
* usou `doc_id` errado no `/ask`
* top_k baixo
* chunks muito grandes/pequenos (ajustar max_words/overlap)

