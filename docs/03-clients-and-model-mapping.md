# 03 · CC Switch、Claude Desktop Code 与 API 客户端

[返回首页](../README.md) · 上一章：[账号轮换](02-accounts-and-rotation.md) · 下一章：[推理强度与核验](04-reasoning-and-model-verification.md)

## 1. 先分清三种凭证

| 名称 | 由谁产生 | 放在哪里 | 用途 |
| --- | --- | --- | --- |
| Codex OAuth 凭证 | 账号授权流程 | VPS `/var/lib/cpa/auths` | CPA 向上游使用该账号 |
| 网关客户端 key | 自己生成 | CPA 配置 + CC Switch/客户端 | 本机调用自己的网关 |
| 官方 Platform API key | OpenAI Platform | 单独的官方 API 客户端 | 按官方 API 用量计费 |

CC Switch 的 Token 框填的是第二种。不要填写 ChatGPT 密码、OAuth refresh token、SSH 密钥。网关 key 可以自行更换，无需重新购买账号。

## 2. URL 写法

| 客户端/用途 | 配置地址 | 最终请求路径 |
| --- | --- | --- |
| Claude Desktop / Claude Code 的 Anthropic Base URL | `https://gateway.example.com` | `/v1/messages` |
| 本仓库 smoke test | `https://gateway.example.com` | 脚本添加 `/v1/responses` |
| 常见 OpenAI SDK `base_url` | `https://gateway.example.com/v1` | SDK 添加 `/responses` |
| 直接 HTTP 请求 | 完整 URL | `https://gateway.example.com/v1/responses` |

不要给 Anthropic Base URL 额外添加 `/v1`，否则某些客户端会请求 `/v1/v1/messages`。OpenAI SDK 是否自行补 `/v1` 取决于 SDK，按实际请求确认。

`127.0.0.1` 始终指运行软件的那台机器。本机 CC Switch 配 localhost 地址时，需要本机确有服务或 SSH 隧道；它不会自动指向 VPS。直接远程连接应填写 VPS 的 HTTPS 域名。

## 3. Claude Desktop 与 Claude Code CLI 分开配置

Claude Desktop 的 Code 页面和命令行 `claude` 是不同入口。只在“Claude Code”分类添加供应商，不一定会修改“Claude Desktop”的连接。应在 CC Switch 左侧选择真正要用的客户端。

本文的桌面步骤适用于具有 Claude Desktop 网关/映射功能的 CC Switch 实例。CC Switch [上游](https://github.com/farion1231/cc-switch) 以及不同分支可能不具有完全相同的 UI。若没有 Claude Desktop 入口，应先确认自己安装的版本和分支，不能假定所有版本都支持。

## 4. 在 CC Switch 添加桌面供应商

1. 备份当前供应商设置，记下原先启用的供应商，便于恢复。
2. 左侧选择 **Claude Desktop**。
3. 新建供应商，名称建议为 **Codex 订阅 · 自建 VPS 网关**。
4. 选择该版本提供的网关/模型映射模式。
5. Base URL 填 `https://gateway.example.com`。
6. Token 填自己在 CPA 设置的客户端 key。
7. 协议选择网关的 **Anthropic Messages 兼容接口**。CPA 已负责转成 Codex 上游协议，不必再给同一路径套第二次 Responses 转換。
8. 填写各桌面角色的显示名称和实际请求模型。
9. 保存并启用这个供应商，按 CC Switch 提示应用设置。
10. 关闭旧 Code 会话，必要时完全退出再启动 Claude Desktop，创建新会话验证。

不要直接编辑 CC Switch 的 SQLite 数据库或仅复制一段 JSON 替换整个 provider 对象。数据库里包含供应商标识、配置元数据和其他应用状态，修改错误可能造成界面正常但实际请求仍走旧供应商。

## 5. 推荐映射

这次实例使用下表。适合想让主 Coding 工作走 `gpt-6.1-sol`，轻量辅助工作走 `gpt-6-luna` 的配置。

| 桌面原生角色 | 菜单显示名称 | 实际请求模型 |
| --- | --- | --- |
| Sonnet | GPT-6.1 Sol | `gpt-6.1-sol` |
| Opus | GPT-6.1 Sol | `gpt-6.1-sol` |
| Fable | GPT-6.1 Sol | `gpt-6.1-sol` |
| Haiku | GPT-6 Luna | `gpt-6-luna` |

角色只是客户端的槽位。界面显示“Opus”，不代表上游仍是 Anthropic Opus。Haiku 角色可能被用于标题、摘要、分类等辅助请求，日志看到 Luna 并不自动代表主任务被降级。

本例原生角色 ID 分别为 `claude-sonnet-5`、`claude-opus-5`、`claude-fable-5`、`claude-haiku-4-5`，见 [映射参考](../examples/desktop-model-routes.json)。这些 ID 会随桌面版变化，应以你的界面/导出配置为准。

保留桌面原生角色有助于客户端沿用自身的能力判断、推理控件和工作流；实际模型转换发生在发送请求时。显示名和实际模型要分别填写，不能只把菜单名称改成 GPT，就认为已完成路由。

如果 CPA 只接 Codex，并由 CC Switch 完成角色到实际模型的映射，通常无需在 CPA 再增加同名 Claude 别名。多供应商环境若必须配置别名，应使用明确且唯一的名称，避免相同别名落到另一个上游。

## 6. 保存后的验证顺序

先发一个短文本请求，确认能返回。再发一个需要读取文件或执行测试的 Coding 请求，验证工具调用。最后比较推理强度和日志里的模型。

| 检查 | 预期 |
| --- | --- |
| 当前启用供应商 | 自建 Codex 网关 |
| 网关请求日志 | `provider=codex`，模型为实际 GPT ID |
| 主任务 | 使用 Sol |
| 辅助请求 | 可使用 Luna |
| 工具调用 | 能继续完成读文件/运行测试等流程 |
| 错误 key | 被拒绝，不应静默回落到别的供应商 |

不同工作流需要的接口不一样，所以 **Cowork 能用不等于 Code 一定能用**。Code 除文本之外依赖工具调用、流式事件、上下文和模型能力判断。若只有 Code 失败，结合第五章定位，不要立刻把原因归结为账号同时登录。

## 7. Claude Code CLI 配置

如果使用命令行客户端，而不是桌面 Code 页面，可使用 [环境变量示例](../examples/claude-code.env.example)。这些是当前 shell 的设置，不会自动改变桌面程序已启动的进程环境。

Windows PowerShell 示例：

```powershell
$env:ANTHROPIC_BASE_URL = 'https://gateway.example.com'
$env:ANTHROPIC_AUTH_TOKEN = 'REPLACE_WITH_YOUR_GATEWAY_KEY'
$env:ANTHROPIC_MODEL = 'gpt-6.1-sol'
$env:ANTHROPIC_DEFAULT_SONNET_MODEL = 'gpt-6.1-sol'
$env:ANTHROPIC_DEFAULT_OPUS_MODEL = 'gpt-6.1-sol'
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL = 'gpt-6-luna'
claude
```

上述 key 是演示占位符；实际输入 key 时避免录屏和保存命令历史。CC Switch CLI 供应商也可管理同类设置，使用它时不要同时留下相互矛盾的全局环境变量。

Claude Code 支持模型别名、环境变量和会话内模型选择，见 [官方模型配置](https://code.claude.com/docs/en/model-config)。`/model` 或 `/status` 可辅助检查客户端选择，但经过映射后，服务端日志更适合确认实际发送的模型 ID。

## 8. OpenAI Responses 客户端

可以直接用 HTTP 请求，不需要 Anthropic 转换入口：

```json
{
  "model": "gpt-6.1-sol",
  "input": "只回复 OK",
  "reasoning": {"effort": "medium"},
  "stream": false
}
```

POST 到 `https://gateway.example.com/v1/responses`，请求头使用 `Authorization: Bearer <网关 key>`。不填写官方 key，除非你的网关另外配置了官方 API 供应商。

本仓库 [smoke_test.py](../scripts/smoke_test.py) 从 `GATEWAY_KEY` 环境变量读取 key，明确只发一次请求，没有失败自动重试。它验证文本连接，不能替代 Claude Code 的工具调用验收。

GPT-6.1 Sol 的官方文档要求工具调用使用 Responses；Chat Completions 对该模型支持文本而不支持工具调用，见 [模型说明](https://developers.openai.com/api/docs/models/gpt-6.1-sol)。Coding 客户端不要因为文本接口能回复，就假定任意协议都能调用工具。

## 9. 更换网关 key 与停用供应商

要换 key，可先在 CPA 的 `access.api-keys` 增加新 key，更新本机客户端并验证，再移除旧 key。多个 key 指向同一个账号池，不代表各 key 自动拥有独立配额隔离。

要回到原供应商，在 CC Switch 启用原供应商，重新应用设置并新建客户端会话。CLI 还需清除对应当前 shell 的环境变量，或关闭该终端。不要只改显示名称。
