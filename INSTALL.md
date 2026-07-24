# EasyStuffFind 无人值守安装

本文件面向安装 Agent。固定服务地址为 `http://127.0.0.1:8733`，固定数据目录为仓库根目录的 `data/`。不要改端口、目录或认证方式。

当用户在某个 OpenClaw agent 的对话中发送仓库地址并说“对接
EasyStuffFind”时，该 agent 必须在自己的 workspace 中执行本文步骤。安装器据此
只绑定当前对话所属 agent，不得让用户选择，也不得批量授权其他 agent。

前置条件：

- macOS 13 或更高版本。
- Docker Desktop 已安装并已启动；Docker Engine 24+，Docker Compose v2。
- 端口 `8733` 未占用。
- 当前用户可写仓库目录。
- OpenClaw CLI 已安装且已有可用 Gateway。

全流程共 5 步。

## 1. 取得仓库

把用户消息中的 GitHub 仓库 URL 原样保存为环境变量后执行：

```bash
test -n "$EASYSTUFFFIND_REPOSITORY_URL" && { test ! -e EasyStuffFind || { echo "FAIL 安装目录已存在：EasyStuffFind"; exit 1; }; } && git clone --depth 1 "$EASYSTUFFFIND_REPOSITORY_URL" EasyStuffFind && cd EasyStuffFind
```

预期输出包含 `Cloning into 'EasyStuffFind'`。验证：

```bash
test -f INSTALL.md && test -f docker-compose.yml && test -f skills/openclaw/SKILL.md
```

命令退出码应为 0。若 `EasyStuffFind` 已存在，输出
`FAIL 安装目录已存在：EasyStuffFind` 并停止，不得覆盖或复用；若 URL 无法访问，报告 Git 错误并停止。

## 2. 运行前置检查

```bash
python3 scripts/preflight.py --port 8733 --data-dir data
```

预期依次出现：

```text
PASS Docker daemon
PASS Docker Compose
PASS 端口 8733 可用
PASS 数据目录可写
PASS 容器用户映射已写入本地 .env（不含 Secret）
```

任何一项 `FAIL` 都必须停止。Docker 缺失时安装并启动 Docker Desktop；daemon 失败时启动 Docker Desktop；端口失败时运行 `lsof -nP -iTCP:8733 -sTCP:LISTEN` 定位并停止占用服务；目录失败时执行 `chmod 700 data` 后重试。最后一项把当前 macOS 用户的 UID/GID 写入被 Git 忽略的 `.env`，不写 token。

## 3. 单命令启动并验证健康

```bash
docker compose up -d --build
```

预期末尾包含 `Started`。验证：

```bash
python3 scripts/wait_for_health.py --url http://127.0.0.1:8733/health --timeout 60
```

预期：

```text
PASS 服务健康：http://127.0.0.1:8733/health
```

若超时，运行 `docker compose logs --tail=100 easystufffind`。出现 `permission denied` 时执行 `chmod 700 data` 后重新运行本步骤；出现端口绑定失败时返回第 2 步，不得自行换端口。

## 4. 闭环自检

```bash
python3 scripts/self_check.py --base-url http://127.0.0.1:8733 --token-file data/api-token
```

预期：

```text
PASS EasyStuffFind 自检：记录 → 别名查询 → 删除闭环通过
```

该脚本读取 token 但不显示 token，并清理测试物品和测试位置。失败时保留错误信息，先确认第 3 步健康，再运行 `docker compose logs --tail=100 easystufffind`；不得仅凭容器为 `running` 宣布成功。

## 5. 安装 OpenClaw Skill 并对接

```bash
python3 scripts/configure_openclaw.py --base-url http://127.0.0.1:8733 --token-file data/api-token
```

预期末尾：

```text
PASS OpenClaw 对接完成；agent=<当前 agent ID>；下一轮对话起可直接使用；token 仅由文件路径引用，未写入配置明文。
```

脚本会根据仓库所在 workspace 自动识别当前 agent，将 Skill 只安装到该
agent，必要时只扩展该 agent 的 Skill allowlist，注入
`EASYSTUFFFIND_BASE_URL` 与 `EASYSTUFFFIND_TOKEN_FILE`，然后验证目标 agent
可见性和一次带认证的只读查询。OpenClaw 会热加载配置和 Skill，不需要重启
Gateway；下一轮对话会取得新 Skill。

如果仓库不在 agent workspace 内且本实例有多个 agent，脚本会明确失败。正在执行
安装的 agent 必须从自己的运行上下文取得 ID，并自行重跑：

```bash
python3 scripts/configure_openclaw.py --base-url http://127.0.0.1:8733 --token-file data/api-token --agent "<当前 agent ID>"
```

使用命名 profile 的 agent 继续沿用进程中的 `OPENCLAW_PROFILE`；无法继承时自行加
`--profile "<当前 profile>"`。不得向用户追问这两个内部标识。任一步失败都不得
宣告完成。

## 对接完成声明

只有第 3、4、5 步全部通过后，Agent 才向用户发送：

```text
EasyStuffFind 已完成安装和对接。
- 服务地址：http://127.0.0.1:8733
- Web 管理端：http://127.0.0.1:8733
- Web 初始账号：`admin`；初始密码：`admin`（首次登录后在账户设置中修改）
- 健康检查：http://127.0.0.1:8733/health
- token 位置：<仓库绝对路径>/data/api-token（未显示内容）
- OpenClaw Skill：easystufffind
- 已绑定 agent：<当前 agent ID>

从下一条消息起，可以在飞书中说“护照放书房书桌第二个抽屉了”、问“护照在哪”，或发送一张照片并说“充电线放这里了”。
```
