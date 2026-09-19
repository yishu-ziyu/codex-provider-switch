# opencode Go 网关协议发现（2026-09-11 实测）

## 网关的配对规则（合成请求验证）

| 输入形状 | 结果 |
|---|---|
| 并行 fc×2 → output×2 连续 | 200 |
| 并行 fc×2 → output1 → **非 output item（如 `<image_resize_notice>`）** → output2 | 400 `No tool output found for tool call <output2 的 call_id>` |
| 同上，但把 notice 移到所有 output 之后 | 200 |
| 单个 output + 其后 notice | 200 |
| 串行 fc1→out1→notice→fc2→out2→notice | 200 |

结论：网关要求同一组 `function_call_output` 连续；任何插在中间的其它 item 会打断后一个调用的配对。notice 出现在 output 之后没有影响，出现在两个 output 之间才致命。

## 线上那次失败的形状

- 会话 ID 已在公开归档中移除；来源 Codex Desktop，cli 0.153.4，2026-09-10T16:21–16:23Z。
- 两个并行 `view_image` → 图片 base64 分别约 692KB / 1.04MB → 各自带 `<image_resize_notice>`（2160×1350 → 1996×1248）→ 400。
- 该错误随后每轮复现（坏历史留在会话里），只能新开会话。

## 当前状态：未能自然复现

用当时那张图的同一份字节（base64 长度 1,041,022）跑真机会话：

| 客户端 | catalog | notice | 错误 |
|---|---|---|---|
| CLI 0.154.0 | 有 | 0 | 0 |
| CLI 0.154.0 | 无 | 0 | 0 |
| app 内置 0.153.4 | 无 | 0 | 0 |

即当前客户端（含 app 内置的 0.153.4 二进制）不再对这批图插入 resize notice，因此触发不到网关的配对缺陷。CLI 0.154.0 的两次真机验证还覆核了并行 `view_image` ×2 与真实图片内容识别。

## 若再次复现，按代价从低到高

1. catalog 里把 `supports_parallel_tool_calls` 设为 `false`，让工具调用串行化（已验证串行形状 200）。代价：失去并行工具调用。
2. 本地转发层重排历史：保持所有 `function_call_output` 连续，把 notice 之类非 output item 移到整组之后（已验证 200）。最接近原生，但需要维护一层代理。
3. 删除 notice（只是缩放提示）。信息有损，但形状也合法。

## session header

- Codex 0.153.4 / 0.154.0 在 `POST /responses` 上都发 `Session-Id`、`Thread-Id`、`X-Client-Request-Id`；opencode 官方文档写明 Go 能识别 Codex 原生 session 头。
- 不要用静态 `x-opencode-session` 覆盖：文档要求"每个对话一个稳定 session id"，静态值会把所有会话压成同一个 id，影响路由与 prompt caching。曾短暂加过，已撤回。
- 只有 `GET /models` 这类辅助请求不带 session 头；它最多影响模型列表刷新，不影响对话本身。

## 用法陷阱

`-c` 覆盖必须放在子命令之前：

```sh
~/.config/codex-go/codex-go -c 'model="deepseek-v4-pro"' exec -C /path "任务"
```

放在 `exec` 之后（`codex-go exec -c 'model=…'`）会丢掉 launcher 传入的 `model_provider`，请求会打到 OpenAI 并报 `model is not supported when using Codex with a ChatGPT account`。
