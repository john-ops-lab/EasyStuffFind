# EasyStuffFind

家庭物品位置记录工具：说一句话或拍一张照片记住物品放在哪里，以后问一句就能找到。

EasyStuffFind 运行在家里的 Mac mini 上，通过 REST API 为 OpenClaw/飞书提供位置记录与查询；同时提供中文、移动优先的 Web 管理端。服务只面向局域网，不包含账号体系或公网访问能力。

![EasyStuffFind 桌面管理界面](docs/screenshots/desktop.png)

<p align="center">
  <img src="docs/screenshots/mobile.png" width="360" alt="EasyStuffFind 手机管理界面">
</p>

## 能做什么

- 用 `书房-书桌-第二个抽屉` 这样的路径自动创建位置树。
- 按名称和别名查询，明确区分唯一命中、多候选、无结果。
- 允许同名异物；安全 upsert 不会在多候选时猜错。
- 保存一张物品当前位置实景照片，并返回一小时签名 URL。
- 自动记录每次移动的原位置、新位置和时间。
- 按位置反查，Web 端支持多选后批量移动。
- 首次启动自动生成 API token，Agent 可直接读文件完成对接。

## 快速开始

面向全新机器和 OpenClaw 的无人值守安装，请严格执行 [INSTALL.md](INSTALL.md)。

已经安装 Docker 时：

```bash
docker compose up -d --build
python3 scripts/wait_for_health.py
python3 scripts/self_check.py --base-url http://127.0.0.1:8733 --token-file data/api-token
```

打开 [http://127.0.0.1:8733](http://127.0.0.1:8733)。Web 登录时需要数据目录中的 `api-token`；macOS 可用以下命令只复制到剪贴板而不显示：

```bash
pbcopy < data/api-token
```

停止服务不会删除数据：

```bash
docker compose down
```

## 两种 OpenClaw 接入方式

### 场景一：让 OpenClaw 安装 EasyStuffFind 并自动对接

适用于已经装好 OpenClaw，但本机还没有 EasyStuffFind 的新用户。把下面这段话
原样发送给需要使用 EasyStuffFind 的 OpenClaw agent：

```text
请安装并对接这个家庭物品位置工具：
https://github.com/john-ops-lab/EasyStuffFind

请严格按照仓库根目录 INSTALL.md 的 5 个步骤执行：完成前置检查、启动服务、
运行记录→查询→删除自检，并把仓库中的 EasyStuffFind Skill 只绑定到当前对话
所属的 agent。不要授权其他 agent，不要显示或复制 token 明文，不要暴露公网。
只有健康检查、自检、目标 agent 可见性和认证查询全部通过后，才向我声明完成。
```

OpenClaw 会克隆仓库、按 [INSTALL.md](INSTALL.md) 使用 Docker Compose 启动服务，
自动读取 `data/api-token`，安装仓库自带的 Skill，并只绑定当前 agent。完成后，
从下一条消息开始即可记录或查询物品。

### 场景二：EasyStuffFind 已经运行，再让 OpenClaw 对接

适用于 EasyStuffFind 已经通过 Docker 或本机进程运行，之后才安装 OpenClaw 的
情况。先确认 `http://127.0.0.1:8733/health` 可以访问，然后把下面这段话发送给
需要使用它的 OpenClaw agent，并将第一行的路径替换为本机实际项目目录：

```text
请把当前 OpenClaw agent 对接到本机已经运行的 EasyStuffFind。

EasyStuffFind 项目目录：<本机 EasyStuffFind 项目绝对路径>
服务地址：http://127.0.0.1:8733
token 文件：<本机 EasyStuffFind 项目绝对路径>/data/api-token

服务已经安装并运行，不要重新安装或重启 EasyStuffFind，不要重启 OpenClaw
Gateway，不要显示或复制 token 明文。请读取项目中的 INSTALL.md 和
skills/openclaw/SKILL.md，从当前 OpenClaw 运行上下文取得你自己的 agent ID，
然后在项目目录执行：

python3 scripts/configure_openclaw.py \
  --base-url http://127.0.0.1:8733 \
  --token-file data/api-token \
  --agent "<当前 agent ID>"

必须确认健康检查、认证查询、OpenClaw 配置校验以及当前 agent 的 Skill 可见性
全部通过。只绑定当前 agent，不要修改其他 agent。完成后告诉我下一条消息起
可以直接使用。
```

如果使用了 OpenClaw 命名 profile，agent 应从自己的运行环境取得 profile，并在
命令末尾加 `--profile "<当前 profile>"`，不需要让用户选择内部 ID。脚本会安全地
检查 token 文件存在、属于当前用户且权限为 `0600`，并只把 token 文件路径注入
Skill 配置。

两种场景的共同成功标志是：

```text
PASS OpenClaw 对接完成；agent=<当前 agent ID>；下一轮对话起可直接使用；
token 仅由文件路径引用，未写入配置明文。
```

## 本机开发

支持 Python 3.12–3.14：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m easystufffind
```

默认地址为 `http://127.0.0.1:8733`，运行数据位于 `data/`。测试和契约检查：

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q easystufffind scripts tests
.venv/bin/python scripts/export_openapi.py --check
.venv/bin/python -m pip check
```

## OpenClaw

仓库自带 [skills/openclaw/SKILL.md](skills/openclaw/SKILL.md)，覆盖：

- 记录位置、查询位置、移动物品和按位置反查；
- 唯一、多候选、无结果三种查询状态；
- 飞书图片下载、原始字节上传、关联和确认；
- 中文确认及消歧话术。

如需手动执行对接脚本：

```bash
python3 scripts/configure_openclaw.py --base-url http://127.0.0.1:8733 --token-file data/api-token
```

从某个 OpenClaw agent 的 workspace 执行时，脚本会自动识别并只绑定该
agent；也支持由 agent 自行传入 `--agent` 和 `--profile`。脚本会校验目标 agent
最终可见性、token 文件权限以及一次带认证的只读 API 查询，不复制 token 明文，
也不会给其他 agent 扩权。正常用户优先使用上面的两种自然语言接入方式。

## 数据、备份与安全

完整运行数据只有：

```text
data/
├── api-token
├── easystufffind.sqlite3
└── photos/
```

- `/api/v1/**` 使用长期 Bearer token；`/health` 无需认证。
- token 文件权限为 `0600`，日志仅记录文件路径和不可逆 SHA-256 指纹。
- 照片 URL 使用 HMAC 签名，默认一小时过期，不包含长期 token。
- Docker Compose 使用 `restart: unless-stopped`，Docker Desktop 登录启动后服务会自动恢复。
- 一致性备份与隔离恢复见 [备份恢复 Runbook](docs/runbooks/backup-and-restore.md)。
- 本项目不提供公网安全承诺，不要配置路由器端口转发或公网反向代理。

## API

- 交互文档：`http://127.0.0.1:8733/docs`
- OpenAPI 快照：[contracts/openapi.json](contracts/openapi.json)
- 所有业务接口：`/api/v1/...`
- v1 兼容原则：已发布字段只增不减。

核心资料：

- [产品需求](docs/product/PRD.md)
- [系统架构](docs/architecture.md)
- [运行与交付](docs/operations.md)
- [发布与回滚](docs/runbooks/release-and-rollback.md)
- [项目状态](docs/project-status.md)

## 项目结构

```text
easystufffind/       FastAPI、SQLite 领域逻辑和 Web 管理端
scripts/             自检、契约、安装、备份和恢复工具
tests/               隔离仓库测试与 live API 测试
contracts/           生成的 OpenAPI 契约
skills/openclaw/     随仓库分发的 OpenClaw Skill
docs/                PRD、架构、运维和项目状态
```

## License

[MIT](LICENSE)
