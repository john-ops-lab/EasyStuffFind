# ADR-002：Web 账号会话与物品脑图

- 状态：已接受
- 日期：2026-07-24

## 背景

OpenClaw 需要长期、无人值守的 API token；浏览器用户不应读取或保存该 token。
Web 还需要按位置层级逐步浏览到物品的脑图入口。

## 决策

- OpenClaw/Agent 继续使用数据目录中的长期 Bearer token。
- Web 使用固定单管理员账号，初始账号和密码为 `admin/admin`；密码保存在 SQLite
  的 scrypt 哈希中，登录后可修改，新密码至少 8 位。
- 登录成功签发 30 天 HttpOnly、SameSite=Strict 的 HMAC 签名 Cookie。
- 修改密码递增认证版本，使此前签发的 Web 会话失效。
- 脑图使用原生 HTML/CSS/JS 递归渲染，不引入图形库；默认展示位置树前两级，
  用户可逐级展开至物品，点击物品打开信息弹窗。

## 影响

- SQLite Schema 从 v1 增量升级为 v2，只新增 `web_accounts` 表。
- `/api/v1` 业务接口同时接受 Agent Bearer token 和同源 Web 会话，既保持 v1
  Agent 契约，也避免浏览器接触长期 token。
- 服务仍只面向局域网；首次登录后应立即修改默认密码。

## 回滚

v2 数据库不能由 v0.1.0 直接打开。回滚应用时需恢复升级前备份；位置、物品、
历史和照片数据在 v1 → v2 迁移中不被修改。
