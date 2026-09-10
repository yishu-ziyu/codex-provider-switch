# Codex 客户端行为笔记

这些结论来自 2026-09 在一台 macOS 机器上的实测，环境为 Codex 桌面端（内置 `codex-cli 0.153.4`）与 CLI `0.154.0`。版本会变，请以你本机的行为为准。

## 1. 客户端读同一份配置

桌面端由系统启动，内部再拉起 `codex app-server`，它读的是同一个 `~/.codex/config.toml`。凡是 CLI 能用的 provider 配置，客户端也能用；区别只是客户端不接受启动参数，不能像 CLI 那样用 `-c` 临时覆盖。

验证方式：把根 `model_provider` 指向一个自定义 provider，退出并重开客户端，然后在没有本机转发服务的情况下发起对话。provider 配错时会拿到上游 401，配置正确时正常返回。

## 2. provider 是全局单槽

客户端创建会话时把 `modelProvider` 留空，即使用根配置里的 provider。模型选择器只决定 `model`，不决定 provider。

推论：

- 原生 GPT 模型与第三方模型不能在一个客户端里同时可用。
- 想让两者出现在同一个菜单里，就必须让它们共用同一个 provider 指向（例如一个本机地址），再由那个地址按模型名分流。

## 3. 模型目录只在启动时加载

`model_catalog_json` 决定的模型清单在客户端启动时读取一次。改完目录或 provider 后必须重启客户端，否则选择器里还是旧的。

目录条目缺少字段时 Codex 会退回默认元数据并打印 warning；最小可用字段是 `slug`，建议同时补 `display_name`、`context_window`、`supported_reasoning_levels`，选择器的展示会更完整。

## 4. 协议支持按会话指定 provider，但 GUI 没有入口

app-server 的线程创建参数里有 `modelProvider`（见 `codex app-server generate-json-schema` 输出中的 `v2/ThreadStartParams.json`）。手工构造 `thread/start` 请求并指定 `modelProvider` 与 `model`，可以让单个会话走第三方 provider，其余会话保持原生。

桌面端目前固定传默认值，没有把开关暴露到界面。所以这个能力当前只对自写客户端或直接驱动 app-server 的场景有意义。

## 5. 切换与重启

改根 `model_provider` / `model_catalog_json` 之后必须重启客户端才生效。`scripts/switch-mode.sh` 做的就是：改两三个键、退出客户端、重新打开、发一条系统通知告诉你当前模式。代价是切换会打断正在跑的会话，大约十几秒。

## 6. 其他坑

- 原生专有设置会被忽略。例如 `service_tier`，第三方模型不认时 Codex 会忽略并打印 warning，请求本身不受影响。
- 模型 slug 必须与提供方一致。有的提供方用裸名（`deepseek-flash`），有的用命名空间（`vendor/model`）；写成提供方不认识的名字会得到 4xx，而不是自动回退。
- 不要把 key 写进配置文件。用 `auth.command` 从环境变量或权限为 600 的文件读取，key 不落进配置和日志。
- 目录里没有根 `model` 时，客户端可能把根 `model` 改写成目录里的某个模型。切换模式时请同时改 `model` 与目录，避免两个来源打架。

## 7. 我们期待的原生能力

如果 Codex 客户端将来在模型选择器里开放 per-thread `modelProvider`，上面第 2、3、5 条就都不需要了：一个客户端可以同时挂原生模型与第三方模型，点击即切换，既不需要本机转发，也不需要重启。
