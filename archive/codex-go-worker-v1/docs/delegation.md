# DeepSeek execution and independent review

## Ask before delegating (updated 2026-09-16)

Before starting each new task, ask: “这次任务选择哪种方式：我直接完成、派原生子 Agent，还是派 DeepSeek 子 Agent？” Only dispatch the selected agent type after the user explicitly agrees. Direct execution or no answer means the primary agent handles the work. An explicit request for a mode already supplies the choice. Ask once per task, not at every step or follow-up; ask again for a new task. Do not switch between native and DeepSeek without agreement. The workflow below applies only when DeepSeek was selected.

The execution and independent DeepSeek review workflow below applies only after that task-level agreement.

Use `~/.local/bin/deepseek-worker` for bounded external workers. It launches the existing codex-go route; it is not a native cross-provider child and installs no daemon.

Write a task file containing the goal, relevant prior decisions, applicable project instructions, owned files, prohibited changes, and acceptance criteria. Do not paste the full main conversation or secrets. Use a fresh receipt directory for each execution or review.

```sh
deepseek-worker run --cwd /absolute/project --task-file /absolute/task.md --run-dir /absolute/new-receipt-directory --role execute --max-seconds 1800
deepseek-worker status /absolute/new-receipt-directory
deepseek-worker cancel /absolute/new-receipt-directory
```

## Match capabilities to the assigned task

Before dispatch, include every authorized write directory outside `--cwd` with repeatable `--add-dir /absolute/directory`. The directory must already exist. Extra roots persist for follow-up turns; file ownership still limits which files the task may change. Do not work around missing roots by silently staging a different deliverable.

Pass required project rules and prior decisions using repeatable `--context-file /absolute/file`; the launcher snapshots them into the private run packet. Include the relevant context, not the entire conversation.

For an additional already-configured tool, use `--mcp-config /absolute/task-tools.toml` containing only selected `[mcp_servers.NAME]` settings. Reuse authorized connection settings; do not install infrastructure or load all plugins. Selected servers must connect before execution starts. Preserve the selected connection's tool approval settings. For a task-authorized tool needing approval, explicitly include its per-tool `tools.NAME.approval_mode = "approve"` and an `enabled_tools` allow-list in the task MCP config; do not blanket-approve unrelated tools. The unattended worker cannot answer new approval prompts. Native Computer Use remains the execute default and cannot be overridden through this file. Review mode rejects extra write roots and extra MCPs to preserve its read-only boundary.

Network access is enabled for normal execute and review turns. Filesystem scope, cancellation, and per-execution runtime limits remain enforced. These options apply to new runs; continuing a run preserves the configuration captured when it started.

Run `run` in a tool-managed terminal session so the main agent can continue other work and inspect `status`. A review is another invocation with `--role review`, a new receipt directory, and its own task. The review sandbox is read-only; execution uses workspace-write. File ownership instructions constrain the task but are not a per-file security sandbox.

Each run uses a fresh CODEX_HOME, inherits the user's skill visibility settings, and reuses codex-go authentication at runtime. Execute mode also loads the installed Codex native cua_repl Computer Use runtime by default. It does not copy unrelated MCPs, credentials, or the main conversation. Skills supplied by the host may still be present. Existing model/provider overrides remain owned by codex-go; the launcher refuses a non-DeepSeek route and checks the final session metadata.

## Visible progress panel

For a substantive dispatch, give each run a short user-readable `--title` (for example, `--title '首页实现'` or `--title '首页独立复核'`). New runs register automatically. Run `deepseek-worker panel` to start or reuse the on-demand local panel; open the returned URL in Codex with `open_in_codex`, placement `right`. Reuse an already open panel tab instead of duplicating it. This is a local browser panel, not a native child-agent card. CLI registration alone does not open the Codex UI.

The panel refreshes every two seconds and shows lifecycle, verified model metadata when available, recent actions, result text and available screenshots. It can request cancellation of an active registered run. A returned result is pending main-agent acceptance. Screenshots are limited to the last four images available within the recent event window; no screenshot does not prove Computer Use was absent.

`deepseek-worker panel --add /absolute/old-receipt-directory` registers an older run. No permanent daemon is installed; the loopback server exits after 30 minutes without panel API reads. If the old panel URL stops responding, rerun `deepseek-worker panel` and reopen the returned URL. The URL contains a local access token; keep it and worker receipts private.

## Codex harness and Computer Use

DeepSeek supplies inference; Codex provides execution, file edits, shell commands, sandboxing, MCP tools, and session receipts. Execute mode discovers the installed unified-computer-use manifest at startup and exposes its desktop surface. It does not install another automation stack or enable the dedicated browser surface.

Tool availability is not permission for unrelated UI actions. Name target apps and allowed operations in the task, follow the tool's returned API and app access controls, and verify the result from fresh accessibility state or screenshots. Avoid simultaneous workers controlling the same target app; sequential operation and verification prevent interference.

Review mode deliberately omits mutable Computer Use tools: a read-only shell sandbox does not make a GUI MCP read-only. Review supplied artifacts/screenshots there. An authorized interactive verification should be a separate execute task with explicit scope. `--no-computer-use` explicitly selects a code-only execute task when desired; default execute mode fails visibly if the installed desktop runtime cannot be found instead of silently dropping the capability.

The manifest path and whether Computer Use was enabled are included in status.json. This proves configuration selection, not successful UI operation. A real Calculator path was verified through the default launcher on 2026-09-13; complex visual-only workflows remain untested.

## Interpreting state

- `running`: process has not exited. `phase` distinguishes an observed pending tool from awaiting model/output; neither proves useful progress.
- `needs_attention` after the quiet interval (default 300 seconds): no new structured event has arrived. Inspect events, errors and the task before deciding whether to wait or cancel. Silence can be normal reasoning; it never triggers an automatic kill.
- `supervisor_stale`: no recent status heartbeat; execution state is uncertain. Do not infer process death or kill a PID from this field.
- `deadline_reached`: total runtime budget was exhausted (default 1800 seconds, set proportionally before dispatch). This is a budget stop, not a diagnosis that the model hung. There is no automatic retry.
- `cancelled`: the run's supervisor honored cancellation or was interrupted. A cancel request is cooperative; an orphaned run cannot be killed through a potentially reused PID.
- `observed_failed_turn`: retains a reported model/protocol failure even if the final stop reason is cancellation or deadline. Inspect it alongside the terminal status.
- `completed_unverified`: the process exited successfully, produced a nonempty result, had no reported failed turn, and its model/provider metadata matched. The main agent must still inspect the task's real artifacts and evidence.
- `failed`: execution, protocol, empty-output, or routing check failed. Read the run's errors and report the actual gap.

The receipt directory contains `status.json`, `result.txt`, structured `events.jsonl`, `stderr.log`, task files and the isolated runtime home. It is private to the local user. Keep these files local; inspect and redact before sharing because worker tool output may contain project data.

Cancellation sends termination to the owned process group and escalates remaining same-group descendants. It does not manage unrelated services or processes that deliberately detach into another session. Deadline classification is based on when the supervisor observes completion; it is not a precise model-server completion timestamp.

The reviewer starts with original requirements and actual artifacts. It checks omissions, edge cases and evidence gaps independently. Send concrete defects back for one bounded repair, then let the primary agent resolve disagreements and perform final acceptance; do not repeat whole test suites without a reason.
