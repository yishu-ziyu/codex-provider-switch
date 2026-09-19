# Codex Provider Switch

> **状态：历史归档（2026-09-19）。** 这套直连切换方案及其后续的
> `codex-go-worker-v1` 已从维护者的日常环境退役。当前环境改用 OpenCodex
> 将第三方模型路由为原生 `spawn_agent` 的模型覆盖项。仓库保留用于复盘，
> 不再代表推荐安装方案。最终一代实现见
> [`archive/codex-go-worker-v1`](archive/codex-go-worker-v1/README.md)。

让 Codex 桌面端和 CLI 直连第三方模型（DeepSeek、GLM、Kimi 等），并在原生模型与第三方模型之间一键切换。

> Point Codex (desktop app + CLI) at a third-party model provider, and switch between native OpenAI models and the external model with one click.

## 背景

Codex 只认一个 `model_provider`。原生 GPT 模型走 ChatGPT 登录，第三方模型要另外接。常见做法是在本机跑一个翻译层或路由器，把不同厂商的协议统一起来；但如果你选的提供方本身就说 Codex 想要的 Responses API，就不需要中间服务，改配置直连即可。

这个仓库记录的就是这条直连路线，以及实测出来的 Codex 客户端行为边界。

## 适用范围

- Codex CLI 与 Codex 桌面端（本项目验证于 `codex-cli 0.153.4` / `0.154.0`）
- 提供方支持 Responses API（本文以 OpenCode Go 的 `https://opencode.ai/zen/go/v1` 与 `deepseek-flash` 为例）
- 你持有该提供方的 API key

如果提供方只有 Chat Completions API，你需要一个协议转换层，本项目不覆盖这种情况。

## 快速开始

### 1. 写一个 provider

在 `~/.codex/config.toml` 里加：

```toml
[model_providers.opencode_go]
name = "OpenCode Go"
base_url = "https://opencode.ai/zen/go/v1"
wire_api = "responses"
requires_openai_auth = false
auth.command = "/usr/bin/python3"
auth.args = ["/绝对路径/scripts/auth.py"]
auth.timeout_ms = 5000
auth.refresh_interval_ms = 300000
```

`auth.command` 是 Codex 的取钥方式：命令从标准输出吐出 key，Codex 只把它用在请求头里。不要把 key 写进配置或仓库。

### 2. 准备模型目录

Codex 的模型选择器读 `model_catalog_json`。用 `scripts/make-catalog.py` 生成一份最小目录：

```sh
./scripts/make-catalog.py --slug deepseek-flash --name "DeepSeek V4.1 Flash" --context-window 1000000 --efforts low,high,max > models.json
```

只填 slug 也能跑，缺失的元数据 Codex 会退回默认值，并在日志里给一条 warning。

### 3. CLI 直连

```sh
./scripts/codex-go -C /path/to/project
./scripts/codex-go exec -C /path/to/project '跑一下测试'
./scripts/codex-go resume SESSION_ID
```

入口通过 `-c` 覆盖配置，不动你原来的 `config.toml`，会话仍由原生 Codex 管理。

### 4. 桌面端直连

桌面端读同一份 `~/.codex/config.toml`，把根设置指过去再重启客户端：

```toml
model = "deepseek-flash"
model_provider = "opencode_go"
model_catalog_json = "/绝对路径/models.json"
```

客户端只在启动时加载模型目录与 provider，所以改完要退出重开。

## 一键切换

`scripts/switch-mode.sh` 在两种模式之间切换根配置并重启客户端：

```sh
./scripts/switch-mode.sh toggle      # 在原生与第三方之间切换
./scripts/switch-mode.sh native      # 回到原生 OpenAI
./scripts/switch-mode.sh deepseek    # 切到第三方模型
./scripts/switch-mode.sh native --no-restart   # 只改配置
```

`scripts/build-app.sh` 把它打包成可双击的 `.app`（含图标），放进 `~/Applications`，拖到 Dock 就是一个按钮：

```sh
./scripts/build-app.sh
```

## 作为 Codex Skill 安装

这个仓库本身就是一个 skill：`SKILL.md` 告诉 Codex 怎么先判定适用性、先用覆盖方式验证、再改根配置并验收。

```sh
./scripts/install-skill.sh          # 复制到 ~/.codex/skills/codex-provider-setup
```

装好后新开一个会话，用 `$codex-provider-setup` 显式触发，或直接说“帮我把 Codex 接到 DeepSeek”让它自动匹配。也可以让 Codex 直接从本仓库安装这个 skill。

## 实测结论

1. 桌面端与 CLI 共享 `~/.codex/config.toml`。把根 `model_provider` 指向自定义 provider 后，客户端会直接请求该 provider 的地址；我们在本机没有任何转发服务的情况下拿到了正常回答。
2. provider 是全局单槽。客户端建会话时使用根配置的 provider，模型选择器只换模型、不换 provider，原生模型与第三方模型无法在同一客户端里各走各的。
3. 模型目录在客户端启动时加载一次，改完必须重启。
4. 协议层其实支持按会话指定 provider：app-server 的 `ThreadStartParams` 有 `modelProvider` 字段，手工调用能让单个会话走第三方 provider，但 GUI 没有暴露这个入口。
5. 想做到"在模型菜单里点着切"，需要一个极小的本机回环转发按模型名分流；不想常驻服务，就用上面的双击切换。

更多细节见 [references/client-behavior.md](references/client-behavior.md)、[references/config-snippets.md](references/config-snippets.md) 与 [references/troubleshooting.md](references/troubleshooting.md)。

## 许可

MIT
