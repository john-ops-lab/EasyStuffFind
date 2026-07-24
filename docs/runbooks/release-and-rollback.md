# Runbook：EasyStuffFind 发布与回滚

版本：`0.1.0`

目标环境：GitHub 开源仓库、Mac mini Docker Compose

最后验证：2026-07-24，GitHub 源码仓库首次公开发布

## 1. 发布边界

- 包含：应用源码、Docker/Compose、文档、测试、OpenAPI、OpenClaw Skill。
- 不包含：`data/`、备份、日志、`.env`、真实照片、token 和本机路径。
- 实际创建远端、推送、Release 或修改运行中 Mac mini 需要另行明确授权。

## 2. 发布前门禁

- [ ] 工作区差异与版本已确认。
- [ ] 本地测试、编译、契约、Skill 和 pip 检查通过。
- [ ] Docker 镜像与 Compose 在干净环境通过。
- [ ] 健康、自检、照片直开和手机 UI 通过。
- [ ] 备份与隔离恢复通过。
- [ ] `.gitignore`、实际暂存文件和全部可达历史完成 Secret 扫描。
- [ ] GitHub Actions 真实运行通过。
- [ ] README 截图不含私人数据。

## 3. 发布步骤

| 顺序 | 操作 | 成功标志 | 失败处理 |
|---:|---|---|---|
| 1 | 生成并检查 `contracts/openapi.json` | `--check` PASS | 修复契约漂移 |
| 2 | 运行本地等价 CI | 全部退出码 0 | 停止发布 |
| 3 | 构建并启动候选镜像 | health + self-check PASS | 停止并保留日志 |
| 4 | 创建经审查的 Git 提交和版本标签 | 暂存集合无私密文件 | 删除本地未推送标签后修复 |
| 5 | 推送并观察 GitHub Actions | 远端 CI 绿色 | 不创建 Release |
| 6 | 创建源码 Release | 资产和版本一致 | 撤下错误 Release |

## 4. 发布验证

- `GET /health` 为 200。
- `scripts/self_check.py` PASS。
- 录入、别名查询、同名多候选、照片、移动历史通过。
- OpenClaw Skill 可发现，飞书拍照记录和中文查询通过。
- 日志无 Secret。

## 5. 停止扩散

- 发现 Secret、私人照片/路径、不可恢复迁移、v1 破坏性契约或自检失败时立即停止。

## 6. 回滚

1. 停止候选容器。
2. 如果数据已由候选版本写入，先运行一致性备份。
3. 切回上一已验证镜像/提交。
4. 启动并运行 health、自检和真实只读抽样。
5. 若 Schema 不兼容，不启动旧代码；恢复升级前备份或发布向前修复。

首版 Schema 只有 v1；当前迁移只初始化空库。未来任何 Schema 变更都必须补充前一版本升级与回滚边界。

## 7. 当前验证边界

- GitHub 公开仓库、`main` 推送、远端文件树和 Actions 已验证。
- 尚未创建版本 Tag 或 GitHub Release。
- Docker 候选镜像回滚。
- 飞书真实端到端。
