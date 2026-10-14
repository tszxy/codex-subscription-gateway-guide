# 05 · 明确错误提示与故障定位

[返回首页](../README.md) · 上一章：[强度与模型核验](04-reasoning-and-model-verification.md) · 下一章：[用量与维护](06-usage-and-maintenance.md)

## 1. 为什么多加一个错误代理

CPA 的终止响应可能使用 429、503 或“没有可用认证”等技术描述。一些客户端会自动重试这些状态，桌面页面只显示笼统的 Server error。为了让用户看到“额度耗尽/无可用账号”，本仓库增加一个很小的响应适配层。

它没有账号密码、没有自己的账号池，不执行换号，也没有独立额度 API。它只接收 CPA 最终失败响应，识别部分错误并返回中文提示。正常文本、工具调用与 SSE 经此层转发。

## 2. 错误分类表

| 上游错误 | 返回状态 | 公开错误码 | 处理 |
| --- | --- | --- | --- |
| `usage_limit_reached` / `quota_exceeded` / `insufficient_quota` | 400 | `codex_quota_exhausted` | 提示当前模型可用账号额度耗尽 |
| `auth_unavailable` / `no_available_auth` / `model_cooldown` | 400 | `codex_accounts_unavailable` | 提示可能是额度、冷却或认证问题 |
| 消息包含 all credentials / all auth | 400 | `codex_accounts_unavailable` | 保留“无可用账号”的不确定性 |
| 普通上游 401 | 原样 | 原样 | 不误报额度耗尽 |
| 普通 502 / 未识别 429 等 | 原样 | 原样 | 保留原始错误 |
| 代理连接 CPA 失败 | 502 | `gateway_upstream_unreachable` | 本地服务/连接问题 |
| 代理等待 CPA 响应超时 | 504 | `gateway_upstream_timeout` | 网络/响应等待超时 |

前三类保留 `upstream_code` 与 `upstream_status`，移除 `Retry-After` 相关响应头。HTTP 400 是本项目的终止兼容策略，语义不同于直接返回原始上游限流状态；依赖标准 429 行为的客户端应了解这个变化。

可以用环境变量 `TERMINAL_ERROR_STATUS=429` 改变已识别终止错误的状态，但此时客户端可能恢复自动重试。默认推荐 400；状态是为了减少重试，不是保证所有软件永远不重试。

## 3. 两个用户可见示例

明确额度耗尽：

```text
所有可用 Codex 账号在当前模型上的额度均已用尽，请等待额度重置后重试。
code: codex_quota_exhausted
upstream_status: 429
```

无法确定全部是额度问题：

```text
当前没有可用的 Codex 账号：可能额度已用尽、账号正在冷却或认证失效。
请稍后重试或检查账号状态。
code: codex_accounts_unavailable
```

桌面客户端可能把正文放在“查看详情”里，顶层仍显示 Server error。代理不能直接控制桌面 UI 的错误呈现。如果桌面完全隐藏正文，先在自己的终端请求同一 API，查看结构化错误。

“所有可用账号”来自 CPA 聚合结果，不是本代理对每个账号的实时配额审计。混合原因时必须参考私有管理状态；不要把任何 502、Cloudflare 页或网络断开解释成所有额度用完。

## 4. 流式响应的边界

代理在响应头/正文开始前识别 HTTP 错误，成功响应保持流式转发；SSE 不会先缓存整个成功正文再返回。复制代理示例到生产时，不要在前面添加会等待完整响应的缓冲配置。

若 HTTP 200 的 SSE 流中途发出 error 事件，或上游中途断开，响应头已发送，代理不能再把状态改为 400，也不拼接另一个账号的新响应。此类中途失败由 CPA 和客户端处理，需要独立验收。

## 5. 建议的排查顺序

1. **确认操作入口**：Claude Desktop Code、Cowork、Claude Code CLI 是否为同一配置？
2. **确认供应商**：CC Switch 当前启用的是自建网关吗？是否还保留旧 localhost 地址？
3. **检查公网入口**：DNS/证书/443 能否连接，`/healthz` 是否在线？
4. **检查本地链路**：VPS 内 8318、8317 是否监听，两个 systemd 服务是否运行？
5. **检查 CPA 认证**：客户端 key 正确吗？账号加载了吗？OAuth 是否失效？
6. **检查请求模型**：是否存在、是否有权限、是否被映射到另一个模型？
7. **检查额度/冷却**：明确错误代码与上游重置信息是什么？
8. **检查工具调用**：文本成功但 Code 失败时，核对协议与工具字段。
9. **检查客户端重试**：是否每隔几秒重复请求，是否有自动重试开关？

管理员终端可使用：

```bash
sudo systemctl status cpa codex-error-proxy caddy --no-pager
sudo ss -lntp
sudo journalctl -u cpa --since '10 minutes ago' --no-pager
sudo journalctl -u codex-error-proxy --since '10 minutes ago' --no-pager
sudo journalctl -u caddy --since '10 minutes ago' --no-pager
```

不要将原始日志整体上传。公开诊断只保留时间、状态、脱敏错误代码和模型 ID。

## 6. 常见现象与处理

| 现象 | 可能原因 | 首先做什么 |
| --- | --- | --- |
| localhost:19001 502 | 本机原有代理失效/隧道未运行 | 确认是否应改为 VPS HTTPS 域名 |
| `/healthz` 正常但 Code 失败 | Caddy 正常、内部账号/协议仍失败 | 逐层做真实推理测试 |
| 401 | 错误网关 key 或上游认证失效 | 看错误来自 CPA access 层还是账号层 |
| 404 | Base URL 重复 `/v1`、错误路由 | 查看实际请求路径 |
| 429 / model cooldown | 配额、速率限制、已有冷却 | 核对上游信息，不反复重启 |
| 无可用账号 | 凭证失效、模型不支持、冷却 | 查看私有账号状态 |
| 502 / HTML 错误页 | 反代目标失败、网络或上游保护页面 | 查 Caddy/代理日志和内部端口 |
| Cowork 通而 Code 不通 | 不同接口/能力需求 | 验证工具调用与 SSE |
| 回复说自己是 Claude | 系统提示/角色身份影响 | 查实际模型路由，不靠自述判断 |
| 修改强度无效果 | 字段没发送、预算路径覆盖、旧会话 | 新会话核对字段和转换结果 |
| 一个操作多行相同记录 | 重试/多个转换阶段/辅助请求 | 使用去重查询；准确计数需请求 ID |

登录同一个账号的网页后变得不可用，不能仅凭时间相关性断定“禁止两处登录”。还可能是授权刷新、缓存、Cloudflare、额度或服务故障。应以可复现现象和认证错误为准。

## 7. 全池终止策略如何验证

离线测试用模拟上游返回额度/账号不可用错误，不触碰真实配额：

```bash
python -m unittest discover -s tests -v
```

若要验证 CPA 自身调度，在独立测试实例使用少量获准的测试账号，记录候选数、切换次数、结束时间和最终代码。不要为了测试故意把生产账号额度烧光，也不要将离线代理测试描述成 CPA 已完成真实全池耗尽实验。

服务层 `Restart=on-failure` 是程序崩溃后的进程重启，和一条 API 请求的账号重试是不同机制。看到 systemd 重启不能推断客户端正在无限换号。
