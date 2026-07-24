# ADR-001：采用标准库 SQLite、原生 Web 与签名照片 URL

- 状态：已接受
- 日期：2026-07-23

## 背景

项目需要 REST API、一份 SQLite 数据库、本地照片、移动优先 Web 和 Mac mini 单容器常驻。用户要求依赖少、易维护，并确认 token 不进入照片 URL。

## 决策

- 使用 FastAPI 0.139.2、Uvicorn 0.51.0、Python 3.12。
- 数据访问、迁移、备份、文件写入使用 Python 标准库。
- Web 使用原生 HTML/CSS/JS，通过 v1 API 管理数据。
- 长期 token 只用于 Bearer 认证；照片使用一小时 HMAC 签名 URL。

## 选择理由

- 避免 ORM、迁移框架、模板引擎、multipart 和 Node 构建链。
- SQLite 单文件和照片目录满足家庭规模与可搬迁备份。
- 签名 URL 同时满足浏览器直开和不泄露长期 token。

## 备选方案

- SQLAlchemy + Alembic：扩展性更强，但当前 Schema 和单机规模不抵消依赖与迁移复杂度。
- React + Vite：复杂前端状态更方便，但当前管理流程可由原生 Web 清晰实现。
- 查询参数携带 token：实现简单，但会泄露到历史、日志和转发链路，拒绝采用。

## 影响与代价

- 数据库访问层需自行保证事务和迁移测试。
- 原生 Web 必须保持组件和状态组织清晰，避免单文件失控。
- 签名 URL 在一小时内属于可转发凭证。

## 回滚或替换方式

- 依赖版本通过 `requirements.lock` 回滚。
- 未来需要 ORM 或 SPA 时先保持 `/api/v1` 契约不变，分阶段替换内部实现。
