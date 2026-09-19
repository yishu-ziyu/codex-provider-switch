# Codex Go Worker v1

> **状态：已退役，仅供历史复盘。**
>
> 活跃开发期：2026-09-10 至 2026-09-19。2026-09-19 起，维护者改用
> OpenCodex 将 `opencode-go/deepseek-v4.1-flash` 注入原生 Codex
> `spawn_agent`，不再需要这套独立 worker、网关和切换 App。

## 它解决过什么问题

当时原生 Codex 子代理不能可靠地跨 provider 运行。这个实验保留 Codex 的
执行环境、工具、沙箱和会话协议，只把推理请求送到 OpenCode Go：

- `codex-go`：用配置覆盖启动独立 Codex 会话。
- `go-gateway`：本机回环白名单网关，限制允许访问的模型。
- `deepseek-worker`：有界执行/只读复核、隔离 `CODEX_HOME`、超时、取消、
  状态回执、额外上下文与 MCP 配置。
- `worker-panel`：本地进度面板，显示运行状态、模型元数据、结果和截图。
- Computer Use：执行模式可加载 Codex 原生桌面自动化运行时；复核模式保持
  GUI 工具关闭。

## 为什么退役

OpenCodex 后来可以把第三方模型作为原生 `spawn_agent` 的模型覆盖项注入
Codex。原方案因此多出一套长期维护成本：独立 app-server、认证桥、本机网关、
进度面板、运行回执和全局规则。替代链路通过连接测试并被新 Codex 会话识别后，
这套设施不再承担日常任务。

这不是对原方案失败的否定。它证明了跨 provider 的真实工具往返、同会话恢复、
有界 worker、独立复核和桌面工具接入，也暴露了不少值得保留的边界问题。

## 关键教训

1. 模型名出现在配置里不等于请求真的走到目标 provider；必须核对最终会话元数据
   和网关证据。
2. 持有第三方 provider 的 Codex 进程可能让记忆整理、子代理等后台路径产生意外
   请求与计费，必须检查实际调用链。
3. 子代理继承整段上下文可能迅速放大输入量；隔离上下文、任务边界和运行预算比
   “能启动”更重要。
4. `completed_unverified` 只说明 worker 正常结束，主代理仍须检查实际改动、测试和
   用户路径。
5. 日志、worker receipt 和面板状态会包含项目内容或访问令牌，不能作为公开源码
   一并上传。

## 目录

- `src/`：最终一代核心源码快照。
- `src/config-overrides.json`：去除个人路径后的历史配置；其中的绝对路径占位符
  仅用于解释结构。
- `src/models.json`：当时使用的精简模型目录。
- `docs/delegation.md`：当时的派发、能力与验收协议。
- `docs/acceptance*.md`：代表性验收契约与结论。
- `docs/findings-gateway-protocol.md`：协议边界与失败分析。
- `docs/lessons.md`：受预算约束的失败记录。
- `fixture/`：最小的读、改、测实验夹具。

## 公开归档的删减

以下内容刻意不在仓库中：

- API key、认证缓存及任何真实凭据来源。
- `worker-runs/`、面板令牌、原始会话 JSONL、截图和任务提示。
- 网关日志、launchd 日志、缓存、生成目录和本机备份。
- 个人绝对路径、真实会话 ID 与无助于理解实现的配置快照。

源码是历史快照，不再提供安装、兼容性或安全维护承诺。若要复用其中思路，应重新
评估当前 Codex、OpenCodex 和 provider 的协议与权限边界。
