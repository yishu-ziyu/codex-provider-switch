---
name: codex-provider-setup
description: 让 Codex（桌面端与 CLI）直连支持 Responses API 的第三方模型提供方，并在原生模型与第三方模型之间切换。用户想用 DeepSeek、GLM、Kimi 等模型驱动 Codex，或问“客户端能不能不用官方模型”时使用；提供方只有 Chat Completions API 时不适用，那种情况需要协议转换层。
metadata:
  short-description: Codex 直连第三方模型并一键切换
---

# Codex Provider Setup

目标：让用户机器上的 Codex 用一个第三方提供方跑起来，并且随时能切回原生模型。

## 适用性先判定

开始前确认三件事，任何一条不成立就先说清楚，不要硬做：

1. 提供方支持 Responses API。只有 Chat Completions 的提供方需要额外的协议转换，不属于本技能范围。
2. 用户持有可用的 API key，并同意把它放在环境变量或权限为 600 的文件里。
3. Codex 已安装（`codex --version`），且用户知道改的是用户级 `~/.codex/config.toml`。

## 流程

### 1. 拿到提供方参数

需要：`base_url`、模型 slug（用提供方文档里的准确名字，带不带命名空间前缀要和上游一致）、以及 key 的来源。

### 2. 先用 CLI 验证，不碰用户的默认配置

在用户级配置里加一段 `[model_providers.<id>]`（`wire_api = "responses"`，用 `auth.command` 取钥，见 [references/config-snippets.md](references/config-snippets.md)），然后用 `scripts/codex-go` 或 `codex -c ...` 覆盖方式跑一次真实的最小请求：

```sh
./scripts/codex-go exec -C /tmp 'Reply with exactly: OK'
```

配置能被解析不等于能跑通；必须看到真实的模型回复，或明确的 4xx 及原因。只有这一步通过，才动根配置。

### 3. 生成模型目录

Codex 的模型选择器读 `model_catalog_json`。用 `scripts/make-catalog.py` 生成最小目录；缺字段时 Codex 会退回默认元数据并打 warning，因此 slug 是下限，展示名、上下文长度、推理档位建议补齐。

### 4. 桌面端

桌面端与 CLI 共享同一份 `~/.codex/config.toml`。要让客户端整体切到第三方模型，需要同时设置根 `model`、`model_provider`、`model_catalog_json`，然后重启客户端：目录与 provider 只在启动时加载一次。

改之前先备份配置文件；用户正在跑任务时先说明会打断，再决定是否立即重启。

### 5. 一键切换（可选）

`scripts/switch-mode.sh` 在 `native` / `external` / `toggle` 之间改根配置并重启客户端；`scripts/build-app.sh` 把它打包成带图标的可双击 `.app`。两个脚本都支持用环境变量指定 provider、模型 slug、目录路径和 App 名称。

## 验收

- CLI：覆盖方式的一次真实请求返回内容（不是仅仅配置解析通过）。
- 桌面端：切换后重启，客户端里发起一轮对话能拿到回复；若失败，回退配置并说明卡在哪一步。
- 切换器：两个方向各切一次，确认根配置里 `model` / `model_provider` / `model_catalog_json` 正确增删。

## 边界

- 不要把 key 写进 `config.toml`、日志或仓库；`auth.command` 从环境变量或 600 权限文件读。
- 不要动用户其它配置与项目文件；只改根配置里这三四个键，并在改动前备份。
- 客户端只有一个 provider 槽，原生模型与第三方模型不能在同一客户端同时可用；想“在模型菜单里点着切”需要一个本机回环转发，先和用户确认是否接受常驻服务。
- 提供方参数不确定时先问用户，不要猜模型名或地址。

## 参考

- 配置片段与取钥写法：[references/config-snippets.md](references/config-snippets.md)
- Codex 客户端行为与实测结论：[references/client-behavior.md](references/client-behavior.md)
- 排错对照：[references/troubleshooting.md](references/troubleshooting.md)
