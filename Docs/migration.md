# 🚚 Migração Completa para Servidor Físico (Produção Doméstica)

> Procedimento operacional objetivo para migrar a stack Docker
> (N8N + Postgres + Ollama + Flask + OpenWebUI + Cloudflared)
> para um novo servidor Ubuntu 24.04 LTS.

---

# 🎯 Objetivo

Recriar o ambiente exatamente como está no WSL/local:

* Mesma estrutura
* Mesmos volumes persistentes
* Mesmas variáveis
* Mesmo comportamento
* Sem retrabalho manual

---

# 1️⃣ Preparar Novo Servidor

## Instalar Ubuntu Server 24.04 LTS

Durante instalação:

* Criar usuário padrão
* Ativar OpenSSH
* Definir IP fixo (recomendado)

Após login:

```bash
sudo apt update && sudo apt upgrade -y
```

---

# 2️⃣ Instalar Docker Oficial (RECOMENDADO)

Evitar docker.io padrão. Usar repositório oficial:

```bash
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Adicionar usuário ao grupo docker:

```bash
sudo usermod -aG docker $USER
newgrp docker
```

Testar:

```bash
docker version
docker compose version
```

---

# 3️⃣ Criar Estrutura Base no Servidor

Criar diretório do projeto:

```bash
mkdir -p ~/docker_pjt_n8n
```

---

# 4️⃣ Transferir Projeto

Do ambiente antigo:

```bash
scp -r docker_pjt_n8n usuario@IP_SERVIDOR:/home/usuario/
```

Ou via rsync (recomendado):

```bash
rsync -avz docker_pjt_n8n usuario@IP_SERVIDOR:/home/usuario/
```

⚠ IMPORTANTE:
Transferir também:

* `.env`
* `data/` (volumes persistentes)
* `data/cloudflared/*.json` (credenciais do tunnel)

---

# 5️⃣ Ajustar Permissões (se necessário)

Caso haja erro de permissão nos volumes:

```bash
sudo chown -R $USER:$USER ~/docker_pjt_n8n
```

---

# 6️⃣ Subir Stack

```bash
cd ~/docker_pjt_n8n

docker compose up -d
```

Verificar:

```bash
docker compose ps
docker compose logs -n 50
```

---

# 7️⃣ Validar Serviços

Testar localmente no servidor:

```bash
curl http://localhost:5678
curl http://localhost:8080/health
```

Verificar Ollama:

```bash
docker exec -it srv-ollama ollama list
```

---

# 8️⃣ Firewall (UFW)

Instalar e ativar:

```bash
sudo apt install ufw -y
sudo ufw allow OpenSSH
sudo ufw enable
```

⚠ NÃO abrir portas 80/443 se estiver usando Cloudflare Tunnel.

---

# 9️⃣ SSH Seguro

Copiar chave pública:

```bash
ssh-copy-id usuario@IP_SERVIDOR
```

Editar:

```bash
sudo nano /etc/ssh/sshd_config
```

Alterar:

```
PasswordAuthentication no
PermitRootLogin no
```

Reiniciar:

```bash
sudo systemctl restart ssh
```

---

# 🔟 Validar Cloudflare Tunnel

```bash
docker compose logs -f cloudflared
```

Testar domínio público.

---

# 🧠 Checklist Pós-Migração

* [ ] Containers ativos
* [ ] Dados persistidos
* [ ] N8N acessível
* [ ] Flask funcionando
* [ ] Ollama respondendo
* [ ] Tunnel conectado
* [ ] SSH apenas por chave
* [ ] Firewall ativo

---

# 💾 Backup Recomendado no Novo Servidor

Criar script simples `backup.sh`:

```bash
#!/bin/bash
cd ~/docker_pjt_n8n

docker compose down

tar -czvf backup_$(date +%F).tar.gz data/

docker compose up -d
```

Dar permissão:

```bash
chmod +x backup.sh
```

---

# 🚀 Migração Concluída

Ambiente replicado com sucesso.

A stack é totalmente portátil:

Basta copiar:

* docker-compose.yml
* .env
* data/

E executar:

```bash
docker compose up -d
```

Servidor doméstico pronto para produção segura.
