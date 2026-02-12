# ⚙️ SETUP.md --- Ambiente Local (N8N + Ollama + Cloudflare Tunnel)

> Setup operacional simples\
> Ubuntu 24.04 (WSL2 ou Linux nativo) + Docker

------------------------------------------------------------------------

## 1️⃣ Pré‑requisitos

### Verificar WSL (Windows)

``` powershell
wsl --status
wsl -l -v
```

### Atualizar Ubuntu

``` bash
sudo apt update && sudo apt upgrade -y
```

### Verificar Docker

``` bash
docker version
docker compose version
```

Se houver erro de permissão:

``` bash
sudo usermod -aG docker $USER
newgrp docker
```

------------------------------------------------------------------------

## 2️⃣ Estrutura do Projeto

``` bash
mkdir -p data/{postgres,n8n,ollama,open-webui,cloudflared}
mkdir -p backups
```

------------------------------------------------------------------------

## 3️⃣ Criar .env

``` bash
nano .env
```

Gerar senha forte:

``` bash
openssl rand -base64 24
```

------------------------------------------------------------------------

## 4️⃣ Subir Stack

``` bash
docker compose up -d
docker compose ps
```

------------------------------------------------------------------------

## 5️⃣ Instalar Modelo LLM (8GB RAM)

``` bash
docker exec -it srv-ollama ollama pull llama3.2:3b
docker exec -it srv-ollama ollama run llama3.2:3b
```

------------------------------------------------------------------------

## 6️⃣ Cloudflare Tunnel

Adicionar serviço ao docker-compose.yml:

``` yaml
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

Subir túnel:

``` bash
docker compose up -d cloudflared
```

------------------------------------------------------------------------

## Uso Diário

Subir:

``` bash
docker compose up -d
```

Parar:

``` bash
docker compose down
```

Logs:

``` bash
docker compose logs -f
```

Atualizar imagens:

``` bash
docker compose pull
docker compose up -d
```

------------------------------------------------------------------------

Ambiente pronto para desenvolvimento local.
