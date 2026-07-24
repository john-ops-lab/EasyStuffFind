# I-002：公有云备份分片上传缺少 Content-Length

日期：2026-07-24
状态：已修复并完成真实云端回读验证

## 预期行为

用户点击“立即备份”后，服务先生成本地 ZIP，再把同一文件同步到已配置的公有云
对象存储私有 Bucket，并返回成功。

## 实际行为

云连接测试通过，本地 ZIP 也已生成，但约 14 MiB 的备份上传失败，Web 只显示
“备份失败，请查看日志”。服务日志中的稳定错误为：

```text
MissingContentLength: You must provide the Content-Length HTTP header.
```

## 复现步骤

1. 启用已验证连接正常的 S3 兼容公有云配置。
2. 创建超过 boto3 默认 8 MiB 分片阈值的备份。
3. `upload_file` 自动进入 multipart `UploadPart`。
4. 云端 S3 兼容接口拒绝缺少显式 `Content-Length` 的分片。

## 已确认事实

- `head_bucket` 连接测试成功，凭据、Endpoint、Region 和 Bucket 基本配置有效。
- SQLite 快照、照片复制和本地 ZIP 均成功。
- 失败只发生在 SDK 自动分片上传阶段。
- 阿里云 OSS 文档明确说明缺少请求体长度时返回 411/MissingContentLength。
- boto3 `put_object` 官方接口支持 seekable 文件、显式 `ContentLength` 和
  `ServerSideEncryption="AES256"`。

## 主要假设

| 假设 | 验证方式 | 结果 |
|---|---|---|
| 凭据或 Bucket 错误 | 同配置执行云连接测试 | 排除；测试成功 |
| 本地 ZIP 损坏 | 本地清单和 SHA-256 校验 | 排除；校验成功 |
| 自动分片未携带长度 | 查看真实异常调用栈 | 确认；失败位于 `UploadPart` |
| 单次 PUT 显式长度可兼容 | 回归测试和真实上传/下载 | 确认 |

## 根因

`boto3.client.upload_file` 对超过默认阈值的文件自动采用 multipart。当前公有云
S3 兼容实现要求每个上传请求显式携带 `Content-Length`，而该分片路径没有满足
服务端要求，因此连接测试通过但实际备份失败。

## 修复

- 将云上传改为低层 `put_object`。
- 以只读文件流作为 `Body`，显式传入归档字节数 `ContentLength`。
- 保留 `ContentType=application/zip` 和 `ServerSideEncryption=AES256`。
- 将 botocore 请求/响应校验设置为 `when_required`，避免非 AWS 服务不需要的
  流式校验尾部。
- 新增 9 MiB 回归测试，要求只能调用 `put_object`，并断言长度、类型、对象键和
 服务端加密参数。

## 验证证据

- 修改前新增回归测试稳定报错：Fake client 没有 `upload_file`。
- 修改后全量 25 项测试通过。
- 本机 launchd 服务重启后健康检查通过：v0.3.0 / Schema 2。
- 使用真实已配置云端成功上传 14,728,064 字节备份。
- 随后从云端重新下载到隔离临时目录，ZIP 清单、Schema 和全部 SHA-256 校验通过。
- 云端对象元数据确认 `ServerSideEncryption=AES256`。

## 剩余风险

- 当前单次上传上限由应用限制为 2 GiB，符合家庭数据规模；若未来单份备份超过
  2 GiB，需要实现显式携带长度且经过目标厂商验证的分片上传。

## 长期改进

云连接测试只能证明权限和 Bucket 可达，不能替代实际写入。保留本次真实
“上传 → 回读 → 清单校验”作为云存储兼容性验收标准。
