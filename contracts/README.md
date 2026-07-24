# Contracts

`openapi.json` 是通过 `scripts/export_openapi.py` 从应用代码生成的 v1 HTTP 契约快照。

- 权威来源：`easystufffind/api.py` 中的路由和 Pydantic 模型。
- 生成：`.venv/bin/python scripts/export_openapi.py`
- 检查：`.venv/bin/python scripts/export_openapi.py --check`
- 兼容原则：`/api/v1` 已有请求/响应字段只增不减；破坏性变化进入新版本路径。

不要手工编辑 `openapi.json`。
