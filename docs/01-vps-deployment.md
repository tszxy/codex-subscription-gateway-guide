# 01 · 从零部署 VPS 网关

[返回首页](../README.md) · 下一章：[账号授权与轮换](02-accounts-and-rotation.md)

## 1. 准备条件与填写表

下面以 Debian/Ubuntu、systemd、Python 3.10+ 为例。使用其他系统时，软件安装和用户管理命令需要调整。本章针对新服务器；已有 CPA、Caddy 或其他网站时，应先备份、检查端口，并合并配置。

| 项目 | 示例 | 实际填写位置 |
| --- | --- | --- |
| VPS SSH | `admin@203.0.113.10` | 自己的 SSH 配置；此 IP 仅用于文档 |
| API 域名 | `gateway.example.com` | DNS、Caddyfile、CC Switch |
| CPA 内部端口 | `127.0.0.1:8317` | CPA 配置、错误代理上游 |
| 错误代理内部端口 | `127.0.0.1:8318` | systemd、Caddyfile |
| 网关客户端 key | 自己生成的随机字符串 | CPA `access.api-keys`、客户端 Token |
| OAuth 凭证目录 | `/var/lib/cpa/auths` | CPA `oauth.auth-dir` |
| CPA 程序目录 | `/opt/cpa` | systemd |
| 本仓库目录 | `/opt/codex-gateway` | Python 服务、脚本 |

网关 key、账号 OAuth 凭证、SSH 密钥分别负责不同用途，不应混用。详细区别在第三章。

## 2. DNS 和网络

把 `gateway.example.com` 的 A 记录解析到 VPS IPv4。如果填写 AAAA，IPv6 必须也能连通，否则证书签发或部分客户端连接可能失败。

需要的公网入站端口通常是 SSH 实际端口、TCP 80 和 TCP 443。8317/8318 只在 VPS 内使用，不需要开放公网。证书签发可能使用 80/443 的 ACME 验证，VPS 也需要正常出站 HTTPS。

如果使用云防火墙与系统防火墙，要分别检查。不要在没有放行实际 SSH 端口时直接开启新的默认拒绝规则。

先从本机登录：

```powershell
ssh admin@203.0.113.10
```

下面服务器命令使用 `sudo`；已经是 root 时可以省略。先确认系统、架构和端口：

```bash
cat /etc/os-release
uname -m
sudo ss -lntp
sudo apt update
sudo apt install -y curl ca-certificates python3 python3-venv git unzip
```

本例 `x86_64` 对应 `linux_amd64`；`aarch64` 对应上游的 `linux_aarch64` 发布包。

## 3. 创建服务用户和私有目录

```bash
sudo useradd --system --home-dir /var/lib/cpa --create-home --shell /usr/sbin/nologin cpa
sudo install -d -o root -g cpa -m 0750 /opt/cpa
sudo install -d -o cpa -g cpa -m 0700 /var/lib/cpa/auths
```

若用户已经存在，跳过 `useradd`，先检查 `id cpa`。程序和配置由 root 管理；认证目录允许 cpa 写入，以保存刷新后的 token 与冷却状态。

## 4. 下载固定版本并核对校验值

从 [CPA v8.0.24 Release](https://github.com/router-for-me/CLIProxyAPI/releases/tag/v8.0.24) 下载对应架构的包。本例不用第三方一键脚本，也不自动追踪 latest。

```bash
mkdir -p "$HOME/cpa-download-8.0.24"
cd "$HOME/cpa-download-8.0.24"
curl -fL -o CLIProxyAPI_8.0.24_linux_amd64.tar.gz \
  https://github.com/router-for-me/CLIProxyAPI/releases/download/v8.0.24/CLIProxyAPI_8.0.24_linux_amd64.tar.gz
curl -fL -o checksums.txt \
  https://github.com/router-for-me/CLIProxyAPI/releases/download/v8.0.24/checksums.txt
awk '$2 == "CLIProxyAPI_8.0.24_linux_amd64.tar.gz" {print}' checksums.txt > selected-checksum.txt
test -s selected-checksum.txt
sha256sum -c selected-checksum.txt
tar -tzf CLIProxyAPI_8.0.24_linux_amd64.tar.gz
tar -xzf CLIProxyAPI_8.0.24_linux_amd64.tar.gz
sudo install -o root -g cpa -m 0750 cli-proxy-api /opt/cpa/cli-proxy-api
```

必须看到校验 `OK` 才继续。校验文件与软件来自同一 Release，可检测下载损坏和不匹配；它本身不是独立审计或签名保证。若包内可执行文件名称发生改变，以解压后的文件列表为准。

不要把下载的二进制或认证文件提交到这个仓库。

## 5. 克隆手册与辅助代码

```bash
sudo git clone https://github.com/tszxy/codex-subscription-gateway-guide.git /opt/codex-gateway
sudo chmod -R o+rX /opt/codex-gateway
```

本仓库代码不包含客户端认证信息。安装后保持代码只由管理员修改；服务用户只需读取。Python venv 也由管理员安装，运行服务时不自动更新依赖。

## 6. 配置 CPA

```bash
sudo install -o root -g cpa -m 0640 \
  /opt/codex-gateway/examples/cpa.config.example.yaml /opt/cpa/config.yaml
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
sudo nano /opt/cpa/config.yaml
```

把生成的 key 替换到 `access.api-keys` 中，保存到自己的密码管理器。不要将 key 留在公开截图、命令历史或仓库里。模板中的 `REPLACE_WITH_RANDOM_GATEWAY_KEY` 只是占位符，必须替换。

模板默认管理接口禁用：`management.secret-key` 为空。若后续需要官方管理面板，单独设置管理 key，通过 SSH 隧道访问，保持 Caddy 只公开 `/v1/*`。管理 key 与客户端 key 不同。

新格式的关键对应关系：

| 老配置根级字段 | v8 位置 |
| --- | --- |
| `host` / `port` | `server.host` / `server.port` |
| `api-keys` | `access.api-keys` |
| `auth-dir` | `oauth.auth-dir` |
| `request-retry` | `routing.retry.request-retry` |
| `max-retry-credentials` | `routing.retry.max-retry-credentials` |
| `max-retry-interval` | `routing.retry.max-retry-interval` |
| `debug` / `logging-to-file` | `observability.logs` 下对应字段 |
| `usage-statistics-enabled` | `observability.usage.usage-statistics-enabled` |

早期根级格式仍可能被兼容读取，但不要在同一文件中重复放两个相互矛盾的配置。上游 [config.example.yaml](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.24/config.example.yaml) 是最终依据。

本仓库模板开启 debug 日志供模型查询使用，关闭完整 request log。debug 也可能包含账号标识或其他敏感诊断信息，日志不应公开。若不需要查询可关闭 debug，代价是成功请求的模型路由记录可能减少。

## 7. 授权至少一个账号

此时转到 [第二章](02-accounts-and-rotation.md)，完成 OAuth 授权并确认凭证目录权限。没有账号时 `/v1/models` 可能有目录数据，但推理请求不一定成功；模型列表不是授权成功的充分证据。

建议先只加入一个账号，跑通整个链路，再加第二、第三个账号。这样排查问题时不会同时混入协议、网络、认证和调度四类变量。

## 8. 安装与启动 CPA systemd 服务

```bash
sudo install -m 0644 /opt/codex-gateway/examples/cpa.service /etc/systemd/system/cpa.service
sudo systemctl daemon-reload
sudo systemctl enable --now cpa
sudo systemctl status cpa --no-pager
sudo journalctl -u cpa -n 50 --no-pager
sudo ss -lntp
```

应只看到 CPA 监听 `127.0.0.1:8317`。本模板用 `ProtectSystem=strict`，仅允许写 `/var/lib/cpa`。若 CPA 因缓存、配置自动改写或另一个版本需要写其他目录而启动失败，应查出具体目录并作最小范围调整，不要直接撤掉全部隔离选项。

模板管理 key 为空，不触发明文管理 key 自动改写。如果配置了管理 key，先在受控条件下完成哈希化，或者按上游推荐保存方式调整；服务运行用户默认不能写 `/opt/cpa/config.yaml`。

## 9. 安装错误提示代理

```bash
sudo python3 -m venv /opt/codex-gateway/.venv
sudo /opt/codex-gateway/.venv/bin/python -m pip install -r /opt/codex-gateway/requirements.txt
sudo install -m 0644 /opt/codex-gateway/examples/codex-error-proxy.service \
  /etc/systemd/system/codex-error-proxy.service
sudo systemctl daemon-reload
sudo systemctl enable --now codex-error-proxy
sudo systemctl status codex-error-proxy --no-pager
sudo ss -lntp
```

应监听 `127.0.0.1:8318`。`CPA_UPSTREAM_URL` 设置在 service 中，默认为 `http://127.0.0.1:8317`。这个代理不验证独立 key，而是原样向 CPA 转交认证头，依赖 CPA 的认证。因此不能单独暴露公网。

上游连接等待默认 15 秒，读取等待默认 600 秒。读取等待是单次网络读取的限制，并非整个 Coding 任务的总时间上限。长时间工具调用、客户端自己的超时仍需单独处理。

在 VPS 本地先测试 8317，再测试 8318：

```bash
read -rsp 'Gateway key: ' GATEWAY_KEY
export GATEWAY_KEY
printf '\n'
/opt/codex-gateway/.venv/bin/python /opt/codex-gateway/scripts/smoke_test.py \
  --base-url http://127.0.0.1:8317 --model gpt-6.1-sol
/opt/codex-gateway/.venv/bin/python /opt/codex-gateway/scripts/smoke_test.py \
  --base-url http://127.0.0.1:8318 --model gpt-6.1-sol
unset GATEWAY_KEY
```

每次 smoke test 发送一次小推理请求，会消耗少量真实用量。离线单元测试不会。测试 key 从环境读取，脚本不打印 key。

## 10. 安装 Caddy

使用 [Caddy 官方安装说明](https://caddyserver.com/docs/install#debian-ubuntu-raspbian) 为自己的发行版安装稳定版。以下是 Debian/Ubuntu 的官方仓库安装方式；已安装时不需要重复添加源。

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl gnupg
curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
sudo chmod o+r /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

新站点配置：

```bash
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.before-codex
sudo nano /etc/caddy/Caddyfile
```

复制 [Caddyfile 模板](../examples/Caddyfile)，将域名替换为真实域名。已有网站时添加站点块并保留原网站配置。

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
sudo journalctl -u caddy -n 50 --no-pager
```

公网访问：

```bash
curl -f https://gateway.example.com/healthz
```

`gateway online` 仅证明 Caddy 入口在线，**不是上游账号或模型健康检查**。仍要做带 key 的真实推理请求。

默认使用域名和正常验证的 HTTPS。若只能使用 VPS IP，证书支持取决于证书签发机构、Caddy 版本和 ACME 配置，本文不把 IP 证书作为默认可复制步骤。也不要用 `-k` 作为桌面客户端的长期修复。

## 11. 本机端到端验证

从本机运行 smoke test，将 `--base-url` 改为公网域名，验证同一模型真实返回。然后再接入 CC Switch。

| 层级 | 检查目标 | 失败时优先检查 |
| --- | --- | --- |
| 8317 | CPA + 账号 | 凭证、模型权限、CPA 日志 |
| 8318 | 错误代理 + CPA | Python 服务、上游 URL、代理错误 |
| HTTPS 域名 | Caddy + 代理 | DNS、证书、防火墙、站点块 |
| Claude Desktop Code | 客户端全链路 | 当前供应商、模型映射、实际请求字段 |

请求 `/v0/management`、`/v8/management`、`/docs` 到公网域名应返回 404；内部端口不应能从公网直接连入。带错误网关 key 的 API 请求应被拒绝。

## 12. 与原有 Claude 网页网关共存

如果 VPS 已有另一套 `web2api` 服务，可在独立路径例如 `/claude-web/*` 下反代，Codex 留在 `/v1/*`。二者拥有不同认证凭证、上游账号和额度规则。第三方 Claude 网页站点的“3 小时次数”不等同于 Codex 订阅额度。

为减少误用，最好给两套服务分别配置域名或明显不同的供应商名称。不要将 Claude 网页凭证加入 Codex auth 目录，也不要把旧的 localhost 端口误当作公网网关地址。
