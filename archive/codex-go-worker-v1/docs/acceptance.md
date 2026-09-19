# Codex + OpenCode Go experiment
Change: A separate reusable terminal launcher runs the actual installed Codex main session on OpenCode Go deepseek-flash. Existing default Codex and official DeepSeek configuration remain untouched.
Not this: OpenCode/Pi execution harness; delegated workers; model fallback; successful HTTP alone; mocked evidence as real acceptance.
Evaluator: Main agent plus independent validator assess receipts and reproduce a bounded path.
Required evidence:
1. Redacted real upstream evidence for Go endpoint and exact model, with streamed tool call and subsequent tool result roundtrip. First probe native Responses before adding a conversion layer.
2. Real Codex session reads a fixture, reproduces failing tests, edits only fixture implementation, reruns passing tests. Preserve run/session IDs and tool results.
3. Same Codex session resumed, recalls nonce without restatement and runs tests again.
4. Launcher supports interactive invocation; verify terminal startup. Credentials only read from existing Pi opencode-go entry at runtime, never written/logged. Bind any adapter to loopback, stop its owned process on exit.
5. Compare hashes of existing global config, official DeepSeek config and auth file. Report unrelated concurrent change rather than restoring it.
6. Document exact launch command and limitations. No global daemon/router re-enable, no user project edits.
Budget: max 3 failures for same gate or 5 candidate rounds, then stop and report to main agent. Each failed gate appends check, value and root cause to lessons.md. No full context load or benchmark; each live trial bounded at 180 seconds.
