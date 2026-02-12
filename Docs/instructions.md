# ⚙️ SETUP.md — Ambiente Local (N8N + Ollama + Open WebUI + Cloudflare Tunnel)

> Setup operacional — Ubuntu 24.04 (WSL2 ou Linux nativo) + Docker
> Preparado para futura migração para servidor físico

---

## 1️⃣ Pré-requisitos

### Verificar WSL (Windows)

```powershell
wsl --status
wsl -l -v
```

### Atualizar Ubuntu

```bash
sudo apt update && sudo apt upgrade -y
```

### Verificar Docker

```bash
docker version
docker compose version
```

Se houver erro de permissão:

```bash
sudo usermod -aG docker $USER
newgrp docker
```

---

## 2️⃣ Estrutura do Projeto

```bash
mkdir -p data/{postgres,n8n,ollama,open-webui,cloudflared}
mkdir -p backups
```

Estrutura final:

```
projeto/
├── docker-compose.yml
├── .env
├── data/
│   ├── postgres/
│   ├── n8n/
│   ├── ollama/
│   ├── open-webui/
│   └── cloudflared/
└── backups/
```

---

## 3️⃣ Criar Arquivo .env

```bash
nano .env
```

Gerar senha forte:

```bash
openssl rand -base64 24
```

Exemplo base:

```env
TZ=America/Sao_Paulo

POSTGRES_DB=n8n
POSTGRES_USER=n8n
POSTGRES_PASSWORD=SENHA_FORTE

N8N_ENCRYPTION_KEY=CHAVE_32_CHARS
N8N_BASIC_AUTH_ACTIVE=true
N8N_BASIC_AUTH_USER=admin
N8N_BASIC_AUTH_PASSWORD=SENHA_FORTE

WEBUI_SECRET_KEY=CHAVE_FORTE
```

⚠️ **Nunca versionar o `.env`**

---

## 4️⃣ Subir Stack

```bash
docker compose up -d
```

Verificar status:

```bash
docker compose ps
```

Ver logs:

```bash
docker compose logs -f
```

Parar containers:

```bash
docker compose down
```

Recriar após alteração:

```bash
docker compose down
docker compose up -d
```

---

## 5️⃣ Instalar Modelo LLM (8GB RAM recomendado)

Baixar modelo leve:

```bash
docker exec -it srv-ollama ollama pull llama3.2:3b
```

Testar modelo:

```bash
docker exec -it srv-ollama ollama run llama3.2:3b
```

---

## 6️⃣ Integração N8N → Ollama

Endpoint interno Docker:

```
http://ollama:11434/api/generate
```

Exemplo JSON Body:

```json
{
  "model": "llama3.2:3b",
  "prompt": "Sua pergunta aqui",
  "stream": false
}
```

---

## 7️⃣ Cloudflare Tunnel (modo container)

### Passo 1 — Criar túnel

Criar o túnel no painel **Cloudflare Zero Trust** (feito uma vez no navegador). Após criar, baixe o arquivo de credenciais `.json` e coloque em:

```
./data/cloudflared/
```

### Passo 2 — Adicionar serviço ao docker-compose.yml

```yaml
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: srv-cloudflared
    restart: unless-stopped
    command: tunnel run
    volumes:
      - ./data/cloudflared:/etc/cloudflared
    networks:
      - srv-net
```

### Passo 3 — Criar config.yml

Salvar em `./data/cloudflared/config.yml`:

```yaml
tunnel: NOME_DO_TUNNEL
credentials-file: /etc/cloudflared/SEU_ARQUIVO.json

ingress:
  - hostname: n8n.seudominio.com
    service: http://n8n:5678
  - hostname: ia.seudominio.com
    service: http://open-webui:8080
  - service: http_status:404
```

### Passo 4 — Subir túnel

```bash
docker compose up -d cloudflared
```

---

## 8️⃣ Monitoramento

Ver uso de recursos:

```bash
docker stats
```

Ver containers ativos:

```bash
docker ps
```

---

## 9️⃣ Backup Rápido

```bash
docker compose down
tar -czvf backup_$(date +%F).tar.gz data/
```

---

## 🔁 Migrar Para Outra Máquina

Copiar via SSH:

```bash
scp -r projeto usuario@ip:/home/usuario/
```

Ou via pendrive/rsync. Na nova máquina:

```bash
cd projeto
docker compose up -d
```

---

## 🧠 Uso Diário — Referência Rápida

| Ação | Comando |
|---|---|
| Subir stack | `docker compose up -d` |
| Parar stack | `docker compose down` |
| Ver status | `docker compose ps` |
| Ver logs | `docker compose logs -f` |
| Logs de um serviço | `docker compose logs -f n8n` |
| Reiniciar serviço | `docker restart srv-n8n` |
| Entrar no container | `docker exec -it srv-n8n sh` |
| Uso de recursos | `docker stats` |
| Atualizar imagens | `docker compose pull && docker compose up -d` |

---

## 🌐 Acessos Locais

| Serviço | URL |
|---|---|
| N8N | http://localhost:5678 |
| Open WebUI | http://localhost:3000 |

---

## 🛡️ Boas Práticas

- Nunca expor portas diretamente na internet — usar Cloudflare Tunnel
- Manter backups periódicos dos volumes (`data/`)
- Atualizar imagens mensalmente
- Senhas fortes em todos os serviços (mínimo 16 caracteres)
- Nunca commitar `.env` em repositório

---

## 📌 Próximas Etapas

- [ ] Migrar para servidor físico Ubuntu
- [ ] Configurar SSH seguro (chave pública)
- [ ] Ativar Cloudflare Tunnel em produção
- [ ] Adicionar monitoramento (Uptime Kuma, Portainer)
- [ ] Configurar firewall (UFW)
- [ ] Implementar backup automático

---

## 📐 Arquitetura

```
Usuário
  ↓
N8N (:5678) ←→ Ollama (:11434) ←→ LLM local
  ↓
Postgres (dados persistentes)

Cloudflare Tunnel → expõe N8N e Open WebUI para internet
Volumes Docker → mantêm persistência entre restarts
```