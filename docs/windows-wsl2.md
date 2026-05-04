# Windows · 通过 WSL2 运行

本项目**不支持原生 Windows**。Windows 用户的唯一推荐路径是 WSL2 + Ubuntu。
所有依赖（Redis / MySQL / Neo4j / Python / Node）都跑在 WSL 内部的 Ubuntu，
而前端浏览器和编辑器（VS Code 等）保留在 Windows 一侧 —— 这是一份"Windows 体验，
Linux 引擎"的工作流。

---

## 1. 启用并安装 WSL2

需要 **Windows 11**（任意版本）或 **Windows 10 21H2 及以后**。
以管理员身份打开 PowerShell：

```powershell
wsl --install
```

该单条命令会：
- 启用 "Virtual Machine Platform" 与 "Windows Subsystem for Linux" 两个可选组件
- 下载并安装 WSL2 内核
- 默认安装 Ubuntu 发行版
- 提示重启

重启后再次打开 Ubuntu，会要求设置一个 Linux 用户名 + 密码（与 Windows 账号无关）。

如果 `wsl --install` 报错（旧系统 / 离线环境），手动启用：

```powershell
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
# 重启后：
wsl --set-default-version 2
wsl --install -d Ubuntu-22.04
```

---

## 2. 安装 Ubuntu 22.04（如果默认装的不是它）

打开 Microsoft Store，搜索 "Ubuntu 22.04 LTS"，点击安装。
完成后从开始菜单启动 Ubuntu，初始化用户名密码。

确认版本：

```bash
lsb_release -a
# Description:  Ubuntu 22.04.x LTS
```

---

## 3. 在 WSL 内部按 Linux 步骤部署

进入 Ubuntu shell 后，**完全照抄** [native-setup.md](native-setup.md) 的
"Ubuntu / Debian" 步骤即可：

```bash
sudo apt update
sudo apt install -y redis-server mysql-server python3.11 python3.11-venv

# Neo4j
wget -O - https://debian.neo4j.com/neotechnology.gpg.key | sudo apt-key add -
echo 'deb https://debian.neo4j.com stable 5' | sudo tee /etc/apt/sources.list.d/neo4j.list
sudo apt update
sudo apt install -y neo4j

# Node 20 via nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
exec $SHELL -l
nvm install 20

# 服务启动 —— WSL2 上 systemd 默认已开启（Win11 + 较新 WSL）
sudo systemctl start redis-server mysql neo4j
```

> WSL2 systemd 支持是默认开启的（`/etc/wsl.conf` 中 `[boot] systemd=true`）。
> 如果 `systemctl` 提示 "System has not been booted with systemd"，
> 在 Windows PowerShell 跑 `wsl --shutdown` 然后重开 Ubuntu。

剩余步骤（创建 conda 环境 / `pip install -r requirements.txt` /
`python scripts/init_mysql.py` / `python scripts/import_neo4j.py` /
启动后端 / 启动前端）与 Linux 一致。

---

## 4. 从 Windows 浏览器访问 localhost:3000

WSL2 的网络已自动转发：在 Ubuntu 内部 `npm run dev` 起在 `0.0.0.0:3000` 后，
**直接在 Windows 任意浏览器打开 `http://localhost:3000` 即可**。
后端 8001、Neo4j Browser 7474 同理。

如果发现连不上：
- 确认前端是否绑定到 `0.0.0.0` 而非 `127.0.0.1`（Vite 默认即 `0.0.0.0`，正常）
- 关闭 Windows 防火墙阻止 vEthernet 适配器的策略；或：

  ```powershell
  New-NetFirewallRule -DisplayName "WSL2-loopback" -Direction Inbound -InterfaceAlias "vEthernet (WSL)" -Action Allow
  ```

---

## 5. 文件系统注意事项

**最重要的一条：**

> 把代码放在 **`/home/<user>/`**（WSL 内部 ext4），**不要**放在 `/mnt/c/`。

理由：

| | `/home/<user>/` | `/mnt/c/...` |
|--|------------------|---------------|
| 文件系统 | ext4（原生） | 9P 协议挂载 |
| `git status` 速度 | 毫秒级 | 数秒~数十秒 |
| `npm install` 速度 | 正常 | 慢 5–10 倍 |
| 文件 watcher | inotify 工作 | 经常丢事件 → Vite HMR 失效 |
| 大小写敏感 | 区分（Linux 行为） | 不区分（Windows 行为）→ 导入路径炸 |

推荐：

```bash
cd ~
git clone <repo-url> AIconverstionSys-public
cd AIconverstionSys-public
```

如果你已经把项目克隆到了 `/mnt/c/Users/...`，**移过来**而不是就地用：

```bash
mv /mnt/c/Users/<you>/AIconverstionSys-public ~/
```

### 5.1 编辑：用 VS Code Remote-WSL

VS Code 提供官方扩展 "WSL"。在 Ubuntu 内部 `~/AIconverstionSys-public` 目录下：

```bash
code .
```

VS Code 会自动以 Remote-WSL 模式启动；语法分析、调试、Git 操作全部在 WSL 内执行，
但编辑器 UI 是 Windows 原生窗口。

### 5.2 路径互访（仅作偶尔之需）

- 从 Windows 看 WSL 文件：`\\wsl$\Ubuntu-22.04\home\<user>\` （文件资源管理器地址栏）
- 从 WSL 看 Windows 文件：`/mnt/c/Users/<you>/...`

但日常开发**不要依赖跨界访问**——尤其是不要把 venv / node_modules 写到对面文件系统。

---

## 6. 常见问题

**Q: `wsl --install` 后没有看到 Ubuntu 图标**
A: 在 Microsoft Store 手动搜索 "Ubuntu 22.04 LTS" 安装。

**Q: 启动 systemctl 报 "System has not been booted with systemd"**
A: 在 Windows PowerShell：`wsl --shutdown`，再重开 Ubuntu。
   仍然不行就编辑 `/etc/wsl.conf` 加：

   ```ini
   [boot]
   systemd=true
   ```

**Q: WSL2 占用内存巨大**
A: 在 `%USERPROFILE%\.wslconfig` 设置：

   ```ini
   [wsl2]
   memory=4GB
   processors=4
   ```

   重启 WSL 生效。

**Q: 内网企业代理装不上 apt 源**
A: 在 `/etc/apt/apt.conf.d/95proxies` 写：

   ```
   Acquire::http::Proxy "http://proxy.example.com:8080/";
   Acquire::https::Proxy "http://proxy.example.com:8080/";
   ```

   pip / npm 同理走环境变量 `http_proxy` / `https_proxy`。

**Q: 想直接关闭 Ubuntu 又不想重启电脑**
A: PowerShell 跑 `wsl --shutdown` 关掉 WSL2 子系统；再次打开 Ubuntu 即重新引导。
