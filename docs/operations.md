# EasyStuffFind 运行与交付说明

最后更新：2026-07-24

## 1. 支持范围

- 生产目标：macOS 13+、Docker Engine 24+、Docker Compose v2、Apple Silicon 或 Intel。
- 容器运行时：Python 3.12。
- 本地开发：Python 3.12–3.14。
- 包管理：pip；`requirements.lock` 是可重复安装来源。
- 当前不支持：Windows 原生部署、公网部署、多容器和多进程。

## 2. 从新环境启动

权威安装入口为根目录 [INSTALL.md](../INSTALL.md)，固定端口 8733。

| 操作 | 命令 | 成功标志 |
|---|---|---|
| 前置检查 | `python3 scripts/preflight.py` | 四项 PASS |
| 启动 | `docker compose up -d --build` | 容器 Started |
| 健康 | `python3 scripts/wait_for_health.py` | 服务健康 |
| 闭环验证 | `python3 scripts/self_check.py` | 记录、查询、删除 PASS |
| 停止 | `docker compose down` | 容器停止，`data/` 保留 |

安全清理只删除测试缓存和构建缓存，不删除 `data/`。需要卸载时先按备份 Runbook 导出数据，再由用户明确决定是否删除。

## 3. 当前 Mac 原生常驻服务

当前开发机暂不使用 Docker，由当前用户的 launchd LaunchAgent 常驻运行：

- 服务标识：`com.johnopslab.easystufffind`
- 配置位置：`~/Library/LaunchAgents/com.johnopslab.easystufffind.plist`
- 本机地址：`http://127.0.0.1:8733`
- 局域网地址：使用当前 Mac 的局域网 IP 和端口 `8733`
- 标准日志：`~/Library/Logs/EasyStuffFind.log`
- 错误日志：`~/Library/Logs/EasyStuffFind.error.log`

常用管理命令：

```bash
launchctl print gui/$(id -u)/com.johnopslab.easystufffind
launchctl kickstart -k gui/$(id -u)/com.johnopslab.easystufffind
.venv/bin/python scripts/wait_for_health.py --url http://127.0.0.1:8733/health --timeout 30
```

如项目目录或 `.venv` 位置变化，应先更新 plist 中的绝对路径，再使用
`launchctl bootout` 和 `launchctl bootstrap` 重新加载。停止服务不会删除 `data/`。
Docker 迁移完成前，本节是当前机器的实际运行方式；面向新机器的权威安装主路径仍是
`INSTALL.md` 中的 Docker Compose。

## 4. 配置与 Secret

| 配置项 | 必需 | 默认值 | 敏感 | 来源 |
|---|---:|---|---:|---|
| `EASYSTUFFFIND_DATA_DIR` | 否 | `data` / 容器 `/data` | 否 | 环境变量 |
| `EASYSTUFFFIND_HOST` | 否 | `0.0.0.0` | 否 | 环境变量 |
| `EASYSTUFFFIND_PORT` | 否 | `8733` | 否 | 环境变量 |
| `EASYSTUFFFIND_LOG_LEVEL` | 否 | `INFO` | 否 | 环境变量 |
| `EASYSTUFFFIND_UID` / `EASYSTUFFFIND_GID` | Compose 必需，自动生成 | 当前 macOS 用户 | 否 | `preflight.py` 写入本地 `.env` |
| API token | 是，自动生成 | 无 | 是 | `<data>/api-token` |

- 示例配置：`.env.example`，不含 Secret。
- 本地配置：进程环境；应用不自动读取 `.env`。
- 容器配置：`docker-compose.yml`。
- Agent：只获得 token 文件路径并在 HTTP 客户端内读取。
- 日志禁止认证头、token、请求体和照片签名查询参数；只记录 URL path。

## 5. 数据与迁移

- 持久化数据：`easystufffind.sqlite3`、`photos/`、`api-token`。
- Schema 权威来源：`easystufffind/database.py`，版本为 `PRAGMA user_version = 1`。
- 启动自动初始化空库；高版本数据库会安全拒绝启动。
- 备份与恢复：[backup-and-restore.md](runbooks/backup-and-restore.md)。
- 空库初始化：由仓库和 live API 测试覆盖。
- 上一版本升级：v0.1.0 是首版，无上一支持版本，不适用。

## 6. 基础 CI

- 平台：GitHub Actions，`.github/workflows/ci.yml`。
- 本地等价命令：

```bash
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m compileall -q easystufffind scripts tests skills/openclaw/scripts
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/export_openapi.py --check
.venv/bin/python scripts/validate_skill.py skills/openclaw
.venv/bin/python -m pip check
```

- 触发：push 和 pull request。
- CI 不使用 Secret、不部署、不访问真实数据。
- 真实远端 CI：尚未运行，仓库未推送。

## 7. 错误日志

- 输出：容器标准输出；查看 `docker compose logs --tail=100 easystufffind`。
- 格式：ISO 时间、级别、logger、`event`、`request_id`、method、path、status、耗时。
- 默认级别：INFO，可由环境变量设置。
- 禁止：Authorization、token、查询字符串、请求体、照片内容和备注。
- 已验证失败：未认证 API 返回 401，日志不含 token；live API 测试在进程退出时做明文泄露断言。

## 8. 发布与回滚

- 目标：GitHub 开源仓库与 Mac mini Docker Compose。
- Runbook：[release-and-rollback.md](runbooks/release-and-rollback.md)。
- 发布成功：健康、自检、照片直开、备份验证。
- v1 Schema 只做向前兼容；首版没有旧 Schema 升级。

## 9. 常见故障

| 现象 | 首先检查 | 固定处理 |
|---|---|---|
| 健康检查超时 | `docker compose logs --tail=100 easystufffind` | 修复日志首个 ERROR 后重启 |
| 401 | token 文件与 OpenClaw 注入路径 | 重跑 `configure_openclaw.py` |
| Skill 全局可见但目标 agent 不可用 | 安装命令是否绑定当前 agent | 在该 agent workspace 重跑，或由 agent 自行传入 `--agent <当前 ID>` |
| 数据目录无权限 | `ls -ld data` | `chmod 700 data` |
| 8733 绑定失败 | `lsof -nP -iTCP:8733 -sTCP:LISTEN` | 停止占用服务后重启 |
| 照片 403 | URL 已过期 | 重新查询物品取得新 URL |
| 数据库版本过高 | 启动日志 | 恢复匹配应用版本或升级应用，不降级数据库 |

## 10. 尚未验证

- 当前开发机没有 Docker，尚未实跑镜像和 Compose。
- 尚未在干净 macOS + 全新 OpenClaw + 飞书进行真实端到端。
- 尚未运行 GitHub 远端 CI。

OpenClaw 对接脚本的隔离测试已覆盖：workspace 自动识别当前 agent、显式
allowlist 最小追加、命名 profile 透传、重复安装覆盖、目标 agent 可见性验证、
认证查询和 token `0600` 检查。它不修改其他 agent，也不重启当前 Gateway。

## 11. 交付门禁

- 实施前检查器：退出码 1；空项目 8 项失败。
- 交付前检查器：退出码 0；12 PASS、0 WARN、0 FAIL。
- 隔离恢复已按备份 Runbook 实跑，健康、自检、原有记录与签名照片均验证通过。
- 53 个候选公开文件的脱敏 Secret 扫描：0 命中；本机绝对路径扫描：0 命中。
- 当前允许结论：实现完成，交付验证未完成。未完成项见第 9 节。
