# 🚚 MIGRATION.md --- Migração para Servidor Físico

------------------------------------------------------------------------

## 1️⃣ Preparar Novo Servidor

Atualizar sistema:

``` bash
sudo apt update && sudo apt upgrade -y
```

Instalar Docker:

``` bash
sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
```

------------------------------------------------------------------------

## 2️⃣ Transferir Projeto

Via SCP:

``` bash
scp -r projeto usuario@IP_SERVIDOR:/home/usuario/
```

Ou via rsync:

``` bash
rsync -avz projeto usuario@IP_SERVIDOR:/home/usuario/
```

------------------------------------------------------------------------

## 3️⃣ Subir Stack

``` bash
cd projeto
docker compose up -d
docker compose ps
```

------------------------------------------------------------------------

## 4️⃣ Firewall Básico

``` bash
sudo apt install ufw -y
sudo ufw allow OpenSSH
sudo ufw enable
```

------------------------------------------------------------------------

## 5️⃣ SSH Seguro

``` bash
ssh-copy-id usuario@IP_SERVIDOR
```

Editar /etc/ssh/sshd_config:

    PasswordAuthentication no

Reiniciar:

``` bash
sudo systemctl restart ssh
```

------------------------------------------------------------------------

Migração concluída.
