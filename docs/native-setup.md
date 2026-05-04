# Linux 原生部署

本文档给出 ScopeGraph 在 Linux 上的部署步骤，覆盖 **Ubuntu 22.04+** 与
**RHEL / Rocky / AlmaLinux 9+**。macOS 用户请直接看 [README](../README.md) 的
"Quick Start"；Windows 用户请看 [windows-wsl2.md](windows-wsl2.md)。

---

## 1. 服务安装矩阵

| 服务 | Ubuntu / Debian | RHEL / Rocky 9+ | macOS（参考） |
|------|------------------|------------------|---------------|
| Redis | `sudo apt install redis-server` | `sudo dnf install redis` | `brew install redis` |
| MySQL | `sudo apt install mysql-server` | `sudo dnf install mysql-server` (NOT `mariadb-server`) | `brew install mysql` |
| Neo4j | 见 §1.1 | 见 §1.2 | `brew install neo4j` |
| Python 3.11 | `sudo apt install python3.11 python3.11-venv` | `sudo dnf install python3.11` | conda |
| Node 20+ | nvm 推荐 | nvm 推荐 | `brew install node` |

> **RHEL 注意**：默认仓库提供 `mariadb-server` 但**不与本项目兼容**（SQLAlchemy
> 异步驱动 `aiomysql` 在 MariaDB 10.4 以下的 prepared-statement 行为有差异）。
> 务必装 `mysql-server`（来自 MySQL 官方 yum 仓库）。

### 1.1 Neo4j on Ubuntu

```bash
wget -O - https://debian.neo4j.com/neotechnology.gpg.key | sudo apt-key add -
echo 'deb https://debian.neo4j.com stable 5' | sudo tee /etc/apt/sources.list.d/neo4j.list
sudo apt update
sudo apt install neo4j
```

### 1.2 Neo4j on RHEL / Rocky

```bash
sudo rpm --import https://debian.neo4j.com/neotechnology.gpg.key
sudo tee /etc/yum.repos.d/neo4j.repo <<'EOF'
[neo4j]
name=Neo4j Yum Repository
baseurl=https://yum.neo4j.com/stable/5
enabled=1
gpgcheck=1
EOF
sudo dnf install neo4j
```

---

## 2. 服务控制

| 操作 | Ubuntu / RHEL（systemd） | macOS（brew） |
|------|---------------------------|----------------|
| 启动 | `sudo systemctl start redis mysql neo4j` | `brew services start redis mysql neo4j` |
| 开机自启 | `sudo systemctl enable redis mysql neo4j` | （brew services 默认已自启） |
| 状态 | `systemctl status neo4j` | `brew services list` |
| 重启 | `sudo systemctl restart neo4j` | `brew services restart neo4j` |
| 日志 | `journalctl -u neo4j -f` | `tail -f $(brew --prefix)/var/log/neo4j/neo4j.log` |

> Ubuntu 上 redis 的 systemd unit 通常名为 `redis-server`；
> RHEL 上则是 `redis`。请用 `systemctl list-units | grep -E '(redis|mysql|neo4j)'` 确认。

---

## 3. 默认端口与验证

| 服务 | 端口 | 验证命令 |
|------|------|----------|
| Redis | 6379 | `redis-cli ping`  → `PONG` |
| MySQL | 3306 | `mysqladmin -uroot -p ping`  → `mysqld is alive` |
| Neo4j Bolt | 7687 | `cypher-shell -u neo4j -p '<pwd>' "RETURN 1"` |
| Neo4j HTTP | 7474 | `curl -s http://localhost:7474/` |
| 后端 FastAPI | 8001 | `curl http://localhost:8001/health/detailed` |
| 前端 Vite | 3000 | `curl -I http://localhost:3000/` |

如果 cypher-shell 不在 PATH：

```bash
# Ubuntu
which cypher-shell || sudo apt install cypher-shell
# RHEL
which cypher-shell || sudo dnf install cypher-shell
```

初次启动 Neo4j 必须改密码：

```bash
cypher-shell -u neo4j -p neo4j -d system \
  "ALTER CURRENT USER SET PASSWORD FROM 'neo4j' TO 'change-me';"
```

初次启动 MySQL 设置 root 密码（Ubuntu/Debian 版常已默认 root 用 socket 验证）：

```bash
sudo mysql_secure_installation
```

---

## 4. 常见坑

### 4.1 firewalld 拦截端口（RHEL / Rocky）

`firewall-cmd --state` 若返回 `running`，需要放行端口或干脆只让本机访问：

```bash
# 放行 7474 / 7687 / 8001 / 3000（仅 localhost 不需要放行；远程访问才需要）
sudo firewall-cmd --add-port=8001/tcp --permanent
sudo firewall-cmd --add-port=3000/tcp --permanent
sudo firewall-cmd --reload
```

> 推荐**不要**对外暴露 7687 / 7474 / 3306 / 6379；只暴露 8001 + 反代。

### 4.2 SELinux 阻止 Neo4j 写日志（RHEL / Rocky）

观察症状：`systemctl start neo4j` 返回 `permission denied` 写 `/var/log/neo4j/`。

```bash
# 临时验证
sudo setenforce 0
sudo systemctl start neo4j
# 确认是 SELinux 后，长期方案：
sudo setsebool -P httpd_can_network_connect 1
sudo restorecon -Rv /var/log/neo4j /var/lib/neo4j
sudo setenforce 1
```

### 4.3 mysql-server vs mariadb-server

如前所述，必须使用 MySQL（不是 MariaDB）。检查：

```bash
mysql --version
# mysql  Ver 8.0.x for Linux ...   ← OK
# mysql  Ver 15.1 Distrib 10.x-MariaDB ...   ← NOT OK
```

误装了 mariadb：

```bash
# Ubuntu
sudo apt purge mariadb-server mariadb-client
sudo apt install mysql-server
# RHEL
sudo dnf remove mariadb-server
sudo dnf install mysql-server
```

### 4.4 Python 3.11 不在默认仓库（旧版 RHEL 8）

```bash
sudo dnf install -y dnf-plugins-core
sudo dnf module enable python311 -y
sudo dnf install python3.11
```

如仍找不到，使用 conda（推荐）：

```bash
curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p $HOME/miniconda3
$HOME/miniconda3/bin/conda init
exec $SHELL -l
conda create -n aics python=3.11 -y
conda activate aics
```

### 4.5 systemd `Type=simple` vs `Type=forking`

如手动用 systemd 托管 uvicorn / vite，建议用 `Type=simple` + `Restart=on-failure`，
否则进程组管理会和 reload 行为冲突：

```ini
[Unit]
Description=ScopeGraph backend
After=network.target redis.service mysql.service neo4j.service

[Service]
Type=simple
User=aics
WorkingDirectory=/opt/aics/backend
Environment="PATH=/home/aics/miniconda3/envs/aics/bin"
ExecStart=/home/aics/miniconda3/envs/aics/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### 4.6 ulimit / open files

Neo4j 在导入大批量 CSV 时会触发 "too many open files"：

```bash
# /etc/security/limits.conf
neo4j    soft    nofile  60000
neo4j    hard    nofile  60000
# 重新登录生效；或重启 neo4j 服务
```
