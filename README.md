# 🏠 Servidor Doméstico — N8N + IA Local + Flask + Cloudflare

Projeto pessoal de laboratório e futura produção doméstica.

Objetivo: manter uma stack modular, portátil e segura, totalmente containerizada.

---

# 🎯 Objetivo do Projeto

Criar um servidor doméstico capaz de:

* Executar automações (N8N)
* Rodar IA local (Ollama)
* Integrar modelos externos (OpenRouter)
* Expor API própria (Flask)
* Publicar serviços via Cloudflare Tunnel
* Migrar facilmente para servidor físico Linux

Tudo via Docker Compose.

---

# 🧱 Arquitetura Geral

```
Internet
   ↓
Cloudflare
   ↓
Cloudflare Tunnel (cloudflared container)
   ↓
Docker Network (srv-net)
   ├── N8N (5678)
   ├── Flask API (8080)
   ├── Open WebUI (3000 → 8080 interno)
   ├── Ollama (11434)
   └── Postgres (5432)
```

Nenhuma porta é exposta diretamente ao público quando em produção.

---

# 📦 Estrutura de Diretórios

```
docker_pjt_n8n/
 ├── docker-compose.yml
 ├── .env
 ├── .env.example
 ├── README.md
 ├── apps/
 │   └── flask/
 │       ├── Dockerfile
 │       ├── requirements.txt
 │       └── src/app.py
 ├── data/
 │   ├── postgres/
 │   ├── n8n/
 │   ├── ollama/
 │   ├── open-webui/
 │   └── cloudflared/
 └── backups/
```

---

# 🐳 Serviços

## 1️⃣ Postgres

* Banco persistente do N8N
* Volume: `data/postgres`

## 2️⃣ N8N

* Automação principal
* Autenticação básica ativada
* Conectado ao Postgres

Acesso local:

```
http://localhost:5678
```

## 3️⃣ Ollama

* IA local
* Modelo padrão: `llama3.2:3b`
* Comunicação interna via `http://ollama:11434`

## 4️⃣ Open WebUI

* Interface visual para Ollama
* Acesso local:

```
http://localhost:3000
```

## 5️⃣ Flask API

* API própria
* Endpoint:

```
POST /generate
```

* Faz proxy para Ollama

Acesso local:

```
http://localhost:8080
```

## 6️⃣ Cloudflared

* Responsável por expor subdomínios
* Usa `config.yml` em `data/cloudflared`

---

# 🔄 Fluxos Principais

## Fluxo 1 — Automação com IA Local

```
Trigger (N8N)
   ↓
HTTP Request
   ↓
Ollama (local)
   ↓
Resposta JSON
   ↓
Processamento / Armazenamento
```

---

## Fluxo 2 — API Flask com IA

```
Cliente
   ↓
POST /generate
   ↓
Flask
   ↓
Ollama
   ↓
Resposta JSON
```

---

## Fluxo 3 — Fallback IA Externa

```
N8N
   ↓
Tentar Ollama
   ↓ (erro)
OpenRouter
   ↓
Resposta
```

---

# ⚙️ Comandos Operacionais

Subir stack:

```
docker compose up -d
```

Rebuild após alteração:

```
docker compose up -d --build
```

Parar stack:

```
docker compose down
```

Ver containers:

```
docker compose ps
```

Ver logs:

```
docker compose logs -f
```

Monitorar recursos:

```
docker stats
```

---

# 💾 Backup

Parar containers:

```
docker compose down
```

Gerar backup:

```
tar -czvf backup_$(date +%F).tar.gz data/
```

---

# 🔐 Segurança

* `.env` não versionado
* `data/` ignorado no Git
* N8N com Basic Auth
* Cloudflare Zero Trust (produção)
* Nenhuma porta aberta no roteador

---

# 🚀 Migração Futura

Copiar projeto para novo servidor:

```
scp -r docker_pjt_n8n usuario@servidor:/home/usuario/
```

Subir no novo servidor:

```
docker compose up -d
```

---

# 🧠 Próximos Passos Evolutivos

* Adicionar Proxy Reverso (Caddy/Nginx)
* Adicionar monitoramento (Uptime Kuma)
* Implementar rate limit
* Automatizar backups
* Separar ambiente dev/prod

---

# 📌 Observação Final

Este projeto é modular, portátil e escalável.

Toda lógica roda em containers.
Todo estado persiste via volumes.
Toda exposição externa passa pelo Cloudflare Tunnel.

Objetivo: autonomia total sobre infraestrutura e IA local.
