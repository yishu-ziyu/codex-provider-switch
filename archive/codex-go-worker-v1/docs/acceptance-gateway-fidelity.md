# 验收契约：让 opencode_go 网关路径更接近原生

## 目标（可观察）

同一套原生 Codex harness（`codex-go` 入口）在 opencode_go 网关上完成一次"并行读取两张 >2000px 图片并回答"的回合：

- 会话 JSONL 中同时出现 >=2 条 `function_call(name=view_image)` 与对应 `function_call_output`（image 型）。
- 该回合以文本回答正常结束，不出现 `No tool output found for tool call`。
- 回合后同一 session 可继续下一轮，不需要新开会话。

## 不是这个

- 不算：把并行降级成串行后声称问题解决（除非明确标注为降级并单独记录代价）。
- 不算：协议层合成探针（synthetic curl）单独通过。
- 不算：HTTP 200 或网关回显模型名。

## 判定器

- 会话 JSONL（`~/.codex/sessions/2026/09/11/rollout-*.jsonl`）里统计：view_image 调用数、image 型输出数、`<image_resize_notice>` 数、`No tool output found` 数。
- 进程退出码与最终回答文本。

## 通过条件

1. 真机会话出现 >=2 个 view_image 调用，且每个调用都有 image 型输出。
2. `No tool output found` 计数为 0。
3. 回合结束有文本回答，退出码 0。

## 失败判据

- 出现 `No tool output found`，或回合以 error 结束。
- 只有当轮内实际发生并行调用时才计为"复现成功"；记录该 session id 与时间戳。

## 预算与停机

- 同一 gate 连续 3 次失败即停，把「检查项 / 失败值 / 根因」追加到 `lessons.md` 并升级给用户。
- 每次真机试验 <=180s。
- 不改动全局 `~/.codex/config.toml` 的官方默认轴；仅改 codex-go 入口自己的 overlay。

## 结果（2026-09-11）

- 通过：并行读取两张 2160×1350 图片的三次真实会话（会话 ID 已在公开归档中移除），0 条 resize notice、0 条 `No tool output found`，均有文本回答。
- 未复现：原失败形状（并行图片 output 之间夹 notice）在当前客户端下无法自然触发；用合成请求确认网关规则仍然存在（见 findings-gateway-protocol.md）。
- 未启用降级：并行工具调用保持开启，未引入本地代理。
- 附带通过：`deepseek-v4-flash`、`deepseek-v4-pro` 真机 shell 工具往返。
