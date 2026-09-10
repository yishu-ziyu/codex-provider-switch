# Codex 客户端行为

以下是 2026-09 在 macOS 上对 Codex 桌面端（内置 `codex-cli 0.153.4`）与 CLI `0.154.0` 的实测结论。版本会变，使用前应重新验证关键假设。

## 客户端读同一份配置

桌面端由系统启动，内部拉起 `codex app-server`，读的是同一个 `~/.codex/config.toml`。CLI 能用的 provider，客户端也能用；区别是客户端没有启动参数，不能用 `-c` 临时覆盖，只能改根配置再重启。

## provider 是全局单槽

客户端创建会话时把 `modelProvider` 留空，即使用根配置里的 provider。模型选择器只决定模型，不决定 provider。因此：

- 原生模型与第三方模型不能在同一客户端里同时可用。
- 想让两者出现在同一个菜单里，必须让它们共用同一个 provider 指向（例如一个本机地址），再由它按模型名分流。

## 模型目录只在启动时加载

`model_catalog_json` 在客户端启动时读取一次；改完目录或 provider 必须重启客户端。目录条目缺字段时 Codex 退回默认元数据并打 warning，最小可用字段是 `slug`。

## 协议支持按会话指定 provider

`codex app-server generate-json-schema` 输出里的 `v2/ThreadStartParams.json` 有 `modelProvider` 字段。手工发起 `thread/start` 并指定 `modelProvider` 与 `model`，可以让单个会话走第三方 provider，其余保持原生；桌面端 GUI 目前固定传默认值，没有暴露该入口。

## 其它观察

- 客户端可能把根 `model` 改写成目录里的模型，因此切换时要同时保证 `model` 与目录一致。
- 原生专有设置（例如 `service_tier`）在第三方模型上会被忽略并打 warning，不影响请求本身。
