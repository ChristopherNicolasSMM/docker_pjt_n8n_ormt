# Docker Commands — Cheat Sheet (Compose + Docker)

> Manual rápido para administrar seu stack (containers, portas, logs, build, limpeza).
> Compatível com Docker Compose v2 (`docker compose ...`).

---

## 1) Visão geral / Status

### Containers rodando
```bash
docker ps
```

### Todos os containers (inclui parados)
```bash
docker ps -a
```

### Status do projeto (Compose)
```bash
docker compose ps
```

---

## 2) Portas e conexões

### Ver portas mapeadas por container (resumo)
```bash
docker ps --format "table {{.Names}}\t{{.Ports}}"
```

### Ver detalhes de rede/portas de um container
```bash
docker inspect <container_name_or_id>
```

### Ver portas abertas no host (Linux)
```bash
ss -tulnp
```

### Ver processos usando portas (Linux)
```bash
sudo lsof -i -P -n
```

---

## 3) Logs

### Logs de todos os serviços (Compose)
```bash
docker compose logs
```

### Logs de um serviço específico
```bash
docker compose logs <service>
```

### Logs em tempo real (follow)
```bash
docker compose logs -f <service>
```

### Últimas 100 linhas de um container
```bash
docker logs --tail 100 <container_name_or_id>
```

---

## 4) Subir, parar e reiniciar (Compose)

### Subir tudo em background
```bash
docker compose up -d
```

### Subir apenas um serviço
```bash
docker compose up -d <service>
```

### Parar sem remover recursos
```bash
docker compose stop
```

### Derrubar (remove containers/rede padrão do compose)
```bash
docker compose down
```

### Derrubar e remover volumes (CUIDADO: apaga dados persistidos)
```bash
docker compose down -v
```

### Reiniciar um serviço
```bash
docker compose restart <service>
```

---

## 5) Build / Rebuild de imagens

### Build completo
```bash
docker compose build
```

### Build de um serviço
```bash
docker compose build <service>
```

### Rebuild sem cache (força baixar/recompilar tudo)
```bash
docker compose build --no-cache
```

### Recriar e subir após build
```bash
docker compose up -d --build
```

---

## 6) Entrar no container (shell / debug)

### Abrir bash (se existir)
```bash
docker exec -it <container_name_or_id> bash
```

### Abrir sh (fallback)
```bash
docker exec -it <container_name_or_id> sh
```

### Rodar um comando dentro do container
```bash
docker exec -it <container_name_or_id> ls -la
```

---

## 7) Recursos / performance

### Monitor em tempo real (CPU/RAM)
```bash
docker stats
```

### Snapshot único
```bash
docker stats --no-stream
```

---

## 8) Volumes (dados persistidos)

### Listar volumes
```bash
docker volume ls
```

### Inspecionar volume
```bash
docker volume inspect <volume_name>
```

### Remover volumes não usados (CUIDADO)
```bash
docker volume prune
```

---

## 9) Redes

### Listar redes
```bash
docker network ls
```

### Inspecionar rede
```bash
docker network inspect <network_name>
```

---

## 10) Limpeza (use com cuidado)

### Remover containers parados
```bash
docker container prune
```

### Remover imagens não usadas
```bash
docker image prune
```

### Limpeza geral (containers parados + imagens não usadas + cache)
```bash
docker system prune
```

### Limpeza geral incluindo volumes (CUIDADO: pode apagar dados)
```bash
docker system prune --volumes
```

---

## 11) Diagnóstico rápido (exemplos comuns)

> Ajuste `localhost` e portas conforme seu `docker-compose.yml`.

### Qdrant (porta padrão 6333)
```bash
curl http://localhost:6333/collections
```

### Ollama (porta padrão 11434)
```bash
curl http://localhost:11434/api/tags
```

### Health check da sua API (ex.: Flask)
```bash
curl http://localhost:8000/health
```

---

## 12) “Receitas” do dia a dia

### Ver stack + logs do serviço principal
```bash
docker compose ps
docker compose logs -f <service>
```

### Rebuild rápido de um serviço e subir novamente
```bash
docker compose build <service>
docker compose up -d <service>
```

### Quando “travou” ou ficou inconsistente
```bash
docker compose down
docker compose up -d
```

### Atualizar tudo (rebuild completo)
```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

---

## 13) Dicas úteis

- Prefira `docker compose ...` (Compose v2) ao invés de `docker-compose ...`.
- Se estiver em produção, evite `down -v` e `system prune --volumes` sem backup.
- Para ver nomes exatos de serviços: `docker compose config --services`

```bash
docker compose config --services
```
