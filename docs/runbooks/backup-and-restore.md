# Runbook：EasyStuffFind 数据备份与恢复

最后验证：2026-07-23

验证结果：已对运行中的测试实例执行在线备份，恢复到全新隔离目录并在
`127.0.0.1:18733` 启动；健康检查、自检闭环、2 条原有物品记录和签名照片访问均通过。
测试备份位于被 Git 忽略的 `tmp/`，不属于发布内容。

## 1. 范围

- 数据源：`data/easystufffind.sqlite3`、`data/photos/`、`data/api-token`。
- Schema：`PRAGMA user_version = 1`。
- 工具：Python 3 标准库 SQLite backup API。
- 备份包含 token，目录必须只允许当前用户访问，不得上传公开仓库。

## 2. 一致性与前置

- SQLite 使用在线 backup API，不用普通文件复制冒充一致性数据库备份。
- 照片在数据库快照后复制；家庭低写入量下可在线备份。要求数据库与照片严格同一时点时，先执行 `docker compose stop easystufffind`。
- 默认输出 `backups/`，权限 `0700`；备份 token 权限 `0600`。

检查空间：

```bash
du -sh data
df -h .
```

## 3. 备份

```bash
python3 scripts/backup.py --data-dir data --output-dir backups
```

成功标志：

```text
PASS 备份完成：.../easystufffind-backup-<UTC时间>
已使用 SQLite backup API，并验证数据库完整性和文件校验值。
```

每个备份包含 `manifest.json`，记录 Schema、文件大小和 SHA-256；不记录 token 明文。

## 4. 隔离恢复

选择上一步输出的明确备份目录，恢复到新的空目录：

```bash
python3 scripts/restore.py --backup backups/easystufffind-backup-<UTC时间> --target tmp/restored-data
```

使用不同端口启动隔离实例：

```bash
EASYSTUFFFIND_DATA_DIR=tmp/restored-data EASYSTUFFFIND_HOST=127.0.0.1 EASYSTUFFFIND_PORT=18733 .venv/bin/python -m easystufffind
```

另一个终端验证：

```bash
python3 scripts/wait_for_health.py --url http://127.0.0.1:18733/health
python3 scripts/self_check.py --base-url http://127.0.0.1:18733 --token-file tmp/restored-data/api-token
```

恢复验证完成后停止隔离进程。`restore.py` 拒绝覆盖非空目录。

## 5. 真实恢复

真实恢复属于破坏性操作，必须先获得用户明确授权：

1. `docker compose down` 停止写入。
2. 把当前 `data/` 整体移动到带 UTC 时间的私有保留目录。
3. 对空的 `data/` 执行 `restore.py`。
4. `docker compose up -d`。
5. 执行健康检查和自检，再检查真实物品/照片抽样。

失败时立即停服，把失败恢复目录移开，再把步骤 2 的保留目录移回。

## 6. 保留

- 至少保留最近 7 份和每月 1 份。
- 备份离机存储应使用加密卷。
- 清理前先确认目标是 `backups/easystufffind-backup-*` 的具体目录；不得对仓库根或 `data/` 使用递归删除。

## 7. 已知限制

- 照片与数据库不是跨文件事务；需要零写入窗口时必须先停服。
- 首版没有上一 Schema 版本升级路径。
