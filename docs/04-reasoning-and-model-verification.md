# 04 · 推理强度、实际模型与本机查询

[返回首页](../README.md) · 上一章：[客户端配置](03-clients-and-model-mapping.md) · 下一章：[错误与排障](05-errors-and-troubleshooting.md)

## 1. 模型自己说的名字不可靠

经过协议转换时，Claude Desktop 的系统提示、界面槽位和会话上下文可能仍包含 Claude 身份。模型回答“我是 Claude Opus 5”不能证明服务器真的调用了 Anthropic，也不能证明 GPT 路由失败。

不同证据的意义：

| 证据 | 能说明什么 | 不能说明什么 |
| --- | --- | --- |
| 菜单名称 | 当前显示标签 | 实际上游模型 |
| 角色映射配置 | 预期发往哪个模型 | 请求已经成功执行 |
| 出站请求 `model` | 客户端发送的模型 ID | 上游内部实现 |
| CPA 执行日志 | 网关使用/尝试的上游和模型 | 独立证明上游模型内部身份 |
| 上游响应元数据 | 服务返回的模型字段等 | 第三方无法伪造该字段 |
| 模型自述 | 会话文本回答 | 可靠模型鉴定 |

因此本文的“实际模型查询”准确含义是 **查询网关实际请求/尝试的模型 ID**。它不做模型指纹鉴定，也不承诺每行都是成功完成的请求。

## 2. GPT-6.1 Sol 支持哪些强度

[官方模型文档](https://developers.openai.com/api/docs/models/gpt-6.1-sol) 支持 `low`、`medium`（默认）、`high`、`xhigh`、`max`；不支持 `none`、`minimal`。

| Claude Desktop 控件名称 | 目标 Codex `reasoning.effort` |
| --- | --- |
| Low | `low` |
| Medium | `medium` |
| High | `high` |
| Extra | `xhigh` |
| Max | `max` |

这是目标对应关系。是否最终生效，要看客户端发送的字段、CPA 转换和目标模型的校验结果。不要把“菜单可选”当作已经验证最终出站值。

## 3. 从 Anthropic 请求转换到 Codex

CPA v8.0.24 的 [Codex / Claude 请求转换源码](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.24/internal/translator/codex/claude/codex_claude_request.go) 处理 thinking 与 output_config，并生成 Codex reasoning 设置。另有通用 thinking 处理层负责目标模型校验。

常见示意：

```json
{
  "model": "gpt-6.1-sol",
  "thinking": {"type": "adaptive"},
  "output_config": {"effort": "high"},
  "messages": [{"role": "user", "content": "分析这段代码"}]
}
```

转换目标：

```json
{
  "model": "gpt-6.1-sol",
  "reasoning": {"effort": "high"}
}
```

示意没有列出完整协议字段。实际请求还包括工具、上下文、消息结构等。

- `thinking.type = adaptive/auto`：可结合 `output_config.effort` 转为对应等级。
- `thinking.type = enabled`：可能从 `budget_tokens` 转为等级，此时单独改 output_config 未必覆盖预算路径。
- 关闭 thinking 可能生成不适用于 Sol 的 `none`，后续模型校验/调整以 CPA 实现为准。
- 未传期望字段时会走转换器默认值，不能从界面标签推断。

如果强度不能调整，先检查是否保留原生桌面角色及其能力控件，再检查选定映射。把所有角色直接替换成任意 GPT 名称，可能让桌面版失去原有能力判断。

## 4. 怎样验证强度确实变化

1. 新建测试会话，记下时间，先选择 Medium。
2. 发送一个短且固定的请求，记录客户端发出的 thinking/output_config 字段。
3. 切换 High，再发送同一请求。
4. 在自己的私有诊断环境检查 CPA 最终生成的 `reasoning.effort` 是否对应变化。
5. 若只看到了 UI 变化，就记录为“控件可调整”；未看到最终出站字段时不能写成“完整链路已验证”。

完整请求日志可能包含提示词、代码、工具参数和账号信息，诊断后应关闭，不能上传公开仓库。本仓库的只读查询不读取正文，也**不显示推理强度**；CPA 当前的模型日志不足以可靠提取这个字段。

实例中已观察到桌面控件可从 High 切到 Extra，转换源码支持相应路径；没有把所有强度逐个做真实上游出站断言。公开手册保留这个验证边界。

## 5. VPS 只读模型查询的原理

[codex_model_query.py](../scripts/codex_model_query.py) 读取 `journalctl -u cpa -o json`，只输出：

```json
{"time":"2026-10-13T19:42:44+00:00","provider":"codex","model":"gpt-6.1-sol"}
```

不会返回原始 MESSAGE、账号身份、认证头、提示词和工具内容。为了让成功请求也出现模型日志，模板打开 CPA debug、保持 stdout journald。关闭 debug 后可能只剩部分失败记录，因此“没看到”不等于“没有调用”。

`recent` 查询最近 24 小时中的最多 10,000 条服务日志，取去重后的最后 30 行；高负载时不保证覆盖整整 24 小时。`watch` 只监听启动后的新日志，不重放历史。

## 6. 去重规则

显示键是 **UTC 时间到秒 + provider + model**。同一秒里相同上游和模型只显示一行；不同秒或不同模型继续显示。实时模式的去重集合限制在 4,096 个键，防止长期运行无限增长。

这个规则解决“一次操作出现两三行相同记录”的显示问题，同时也会合并同一秒内真实的不同请求。**显示行数不能用于请求计数、额度扣减或账单核算。** 要准确审计次数，需要请求 ID 或上游交易 ID，而不是秒级去重。

## 7. 创建专用只读 SSH 用户

在 VPS 安装查询脚本：

```bash
sudo install -o root -g root -m 0755 \
  /opt/codex-gateway/scripts/codex_model_query.py /usr/local/bin/codex-model-query
sudo useradd --create-home --shell /bin/sh codex-model-query
sudo usermod -aG systemd-journal codex-model-query
sudo install -d -o codex-model-query -g codex-model-query -m 0700 \
  /home/codex-model-query/.ssh
```

在 Windows 为它生成独立密钥：

```powershell
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\codex_query" -C 'codex-model-query'
```

可使用口令配合 ssh-agent；否则 BatchMode 查询需要可用的无交互 key。无口令私钥要限制 Windows ACL，只允许自己读取。这个 key 只用于查询，不使用 root 的管理私钥。

复制 `.pub` 的一整行到 VPS 的 `/home/codex-model-query/.ssh/authorized_keys`，加上强制命令前缀：

```text
restrict,command="/usr/local/bin/codex-model-query" ssh-ed25519 YOUR_NEW_PUBLIC_KEY codex-model-query
```

```bash
sudo chown codex-model-query:codex-model-query /home/codex-model-query/.ssh/authorized_keys
sudo chmod 0600 /home/codex-model-query/.ssh/authorized_keys
```

`restrict` 限制端口转发、PTY、代理转发等，`command` 强制进入脚本。脚本只允许 `recent` 或 `watch`，不把传入字符串拼接进 shell。用户加入 journal 组是为了读取日志；真正持有普通本地 shell 时该组可能读取更多系统日志，因此不要另给该用户开放普通密码登录或其他非受限 key。

某些系统会拒绝完全锁定账号的 SSH 公钥登录，或没有 systemd-journal 组；应按本机 sshd/PAM 和日志权限作最小调整，不开启这个用户的普通密码登录作为快捷修复。

首次连接前，在可信服务器会话中查看主机公钥指纹，再在本机确认相同指纹，写入 known_hosts。不要通过关掉 StrictHostKeyChecking 绕过这一步。

## 8. 本机配置查询脚本

把 [配置示例](../examples/query-settings.example.json) 复制为 `scripts/query-settings.json`，替换 Host、Port、User、KeyPath。真实配置在 `.gitignore` 中，不应提交。

```powershell
Copy-Item .\examples\query-settings.example.json .\scripts\query-settings.json
notepad .\scripts\query-settings.json
.\scripts\Query-CodexModel.ps1 -Once
.\scripts\Query-CodexModel.ps1 -Watch
```

`KeyPath` 可以使用绝对路径，或相对于脚本目录的路径；示例中的 `YOUR_USER` 必须替换。默认交互模式支持 Enter 刷新、W 实时、Q 退出；实时模式 Ctrl+C 退出。

Windows PowerShell 5.1 的脚本使用 UTF-8 BOM，避免中文乱码。若组织策略限制执行脚本，按自己的组织规定签名或使用允许的启动方式；不要修改全局策略。双击 `.cmd` 使用本进程的执行策略启动此已检查脚本。

推荐检查受限权限：

```powershell
ssh -T -i "$env:USERPROFILE\.ssh\codex_query" codex-model-query@gateway.example.com recent
ssh -T -i "$env:USERPROFILE\.ssh\codex_query" codex-model-query@gateway.example.com id
```

第一条应只返回 JSON 元数据，第二条应拒绝并显示 `Only recent or watch is allowed.`，不会执行 `id`。脚本失败一次就退出，不无限重连。

要做桌面快捷方式，可让目标指向 `Query-CodexModel.cmd`；不要把 key 或 root 密码写进快捷方式参数。修改去重脚本后，已打开的 watch 进程需要关闭重开，才会使用新版本。
