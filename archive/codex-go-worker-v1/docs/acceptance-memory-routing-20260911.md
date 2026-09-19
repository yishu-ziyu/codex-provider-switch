> 历史记录：记忆隔离判断已被源码核验推翻并修正，参见 acceptance-official-memory-startup-20260911.md。凭据恢复和提交推送证据仍有效。

# 任务：恢复受限的 Go 会话，并停止通过 Go 调用记忆模型

- [x] 同一 cmux window:2 / workspace:2 / surface:69 恢复原会话；新凭据读取自 Pi auth，权限 0600，其他凭据项保留。
- [x] 真实主任务 deepseek-flash 请求通过 OpenCode Go 返回 HTTP 200，恢复执行 git 暂存、提交任务。
- [x] 旧日志请求 a39431c9ea15297d-SEA 将 gpt-5.6-luna 发送到 opencode.ai/zen/go/v1/responses，返回 429，并对应记忆 phase1 失败。主任务同时 429；无账单证据证明 Luna 导致额度耗尽。
- [x] 删除 Go 启动器中的 DeepSeek 记忆模型覆盖，设置 memories.generate_memories=false。重启后观察窗口内未再出现 Go 记忆提取请求。
- [x] 当前恢复会话在状态库仍为 memory_mode=enabled；正常官方 Codex 全局 generate_memories=true，未改动。
- [ ] 未强制触发本次会话的官方记忆整理；有空闲时间等调度条件，不能以配置替代实测成功。

限制：新建 Go 会话在此设置下不生成新记忆，已有记忆仍可读取。本版没有独立 memory provider 配置，不能宣称已实现任意 Go 新会话自动交给官方整理。

配置备份为同目录 config-overrides.json.bak-20260911-*；未备份或记录 Key 明文。产品仓库由原会话继续处理，本次修复没有编辑其源文件。

后续核验：原会话完成提交与推送，git ls-remote origin refs/heads/main 返回 6e20ca7d35fcaa1e805153786def677feb6f37b0，与本地 HEAD 一致。
