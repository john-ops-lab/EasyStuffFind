# 任务卡：T-001 首个可运行版本与交付基线

## 目标

- 实现 PRD 中全部 v1 核心能力、移动优先 Web、OpenClaw Skill 和无人值守安装资料。

## 前置条件

- [x] 用户确认六项关键设计决策。
- [x] 实施前交付检查器已运行并记录退出码 1、8 项失败。
- [x] 项目、依赖和交付 Skill 已加载。

## 必读文件

- `docs/product/PRD.md`
- `docs/architecture.md`
- `docs/adr/0001-stack-auth-and-storage.md`

## 允许修改

- 项目内应用、测试、文档、容器、CI、Skill 和契约文件。

## 禁止修改

- `.agents/` 中第三方 Skill 资产。
- 用户已有 `EasyUseAIDE-main.zip`。
- 真实家庭数据和外部服务。

## 业务规则与不变量

- v1 字段只增不减；同名物品允许；多候选 upsert 不写数据。
- token 不输出；照片长期 URL 不包含 token。
- 非空位置不得删除；移动必须有历史。

## 验收命令与预期

| 命令或操作 | 预期结果 |
|---|---|
| `python -m unittest discover -s tests -v` | 全部测试通过 |
| `python -m compileall -q easystufffind scripts tests` | 退出码 0 |
| `python scripts/export_openapi.py --check` | 契约一致 |
| `python scripts/self_check.py ...` | 记录、查询、删除闭环 PASS |
| 桌面/手机浏览器核心流程 | 无溢出，浏览、搜索、编辑、移动可用 |
| 交付检查器 | 无失败 |

## 文档同步

- [x] PRD
- [x] 架构文档与 ADR
- [x] 接口契约与 Schema
- [x] project-status

## 当前结论

- 实现完成，交付验证未完成。
- 本机 API、Web、备份恢复和交付基线已通过。
- OpenClaw 当前 agent 自动识别、最小授权和目标可见性已通过隔离测试。
- GitHub 公开仓库和 Python 3.12 远端 CI 已通过。
- Docker Compose、干净 macOS + OpenClaw + 飞书仍待目标环境验证。

## 风险等级

- 等级：L3
- 判定依据：涉及公共 API、认证、SQLite 持久化、照片文件和部署。
- 是否需要实施前审批：需要；用户已确认推荐方案。
