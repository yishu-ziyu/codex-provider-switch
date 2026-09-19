# 任务：官方 Codex 启动时整理 Go 会话

## 完成标准

- [x] 新 Go 会话保留 memory_mode=enabled。
- [x] Go 启动时关闭内置记忆流水线，不能向 Go 发送后台记忆模型请求。
- [x] 官方启动的记忆候选查询包含其他 provider 的会话；本版源码已核对 provider 不参与筛选。
- [ ] 本次新 Go 测试会话被官方实际整理：尚未达到默认 6 小时空闲条件，不修改时间戳或调度来制造成功。

## 边界

- 不修改正在执行任务的会话，不直接修改历史数据库。
- 保留默认空闲 6 小时、最近 10 天、每次最多 2 条的调度。
- Go 关闭 features.memories 会同时关闭内置记忆摘要注入和专用工具；仍可按需读取记忆文件。
- 上次 generate_memories=false 只控制被整理资格，不能作为禁止后台流水线的依据；修订上次结论。

## 验证证据

- 本机 codex-cli 0.154.0；对应源码 rust-v0.154.0 中 memories/write/src/start.rs 由 features.memories 控制流水线；core/src/session/session.rs 由 generate_memories 控制保存的 memory_mode。
- state/src/runtime/memories.rs 的启动筛选设置 model_providers: None，并要求 memory_mode=enabled。
- app-server/src/request_processors/turn_processor.rs 在实际用户回合开始后触发后台流水线，不是只打开一个空窗口就处理。
- 真实 Go 新会话返回 MEMORY_ROUTE_CHECK_OK（会话 ID 已在公开归档中移除），数据库为 opencode_go / enabled；实际提示中没有内置记忆注入，未认领记忆 job。
- 官方新会话返回同一标记（会话 ID 已在公开归档中移除），数据库为 openai / enabled，保留内置记忆提示；本轮未认领新记忆 job。当前最新的默认合格 Go 候选已完成且 source_updated_at 等于 updated_at。
- 未直接改会话库；44 条已有 Go 会话观察时均为 enabled，不需要迁移。正在工作的 surface:69 没有打断或重启。
- 验证使用现有官方 CLI 的 app-server，同一用户配置及会话库，无第三方模型代理、无新增常驻任务。
