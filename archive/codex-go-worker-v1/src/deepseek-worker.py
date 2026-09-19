#!/usr/bin/env python3
"""Run bounded DeepSeek work through codex-go, with observable local receipts."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import tomllib
import uuid

RUNNING = {"starting", "running"}


def computer_use_config(cache=None):
    """Use the installed Codex desktop runtime, never an independently downloaded bridge."""
    cache = cache or Path.home() / ".codex/plugins/cache/openai-bundled/unified-computer-use"
    candidates = sorted(cache.glob("*/.mcp.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for manifest in candidates:
        server = json.loads(manifest.read_text()).get("mcpServers", {}).get("cua_repl")
        if not server or not Path(server["command"]).is_file():
            continue
        if not server.get("args") or not Path(server["args"][0]).is_file():
            continue
        env = dict(server.get("env", {}))
        env["CUA_REPL_ENABLED_SURFACES"] = "computer"
        text = ("\n[mcp_servers.cua_repl]\ncommand = " + json.dumps(server["command"]) +
                "\nargs = " + json.dumps(server["args"]) +
                '\nenabled = true\nstartup_timeout_sec = 120\nenabled_tools = ["js", "js_reset"]\n' +
                "\n[mcp_servers.cua_repl.env]\n")
        text += "".join(json.dumps(k) + " = " + json.dumps(v) + "\n" for k, v in env.items())
        return text, str(manifest)
    raise ValueError("Installed Codex Computer Use runtime not found. Inspect the installation, or explicitly choose --no-computer-use for a code-only task.")


def save_status(directory, state):
    state["updated_at"] = time.time()
    temp = directory / "status.tmp"
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    temp.replace(directory / "status.json")


def read_status(directory):
    state = json.loads((directory / "status.json").read_text())
    if state.get("format") != "deepseek-worker-v1":
        raise ValueError("Not a DeepSeek worker run directory")
    if state["status"] in RUNNING and time.time() - state["updated_at"] > 15:
        state["supervisor_stale"] = True
        state["needs_attention"] = True
    return state


def stop_owned_process(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    # A leader exiting does not mean its descendants left the process group.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def supervise(command, directory, env, state, quiet_seconds, max_seconds):
    """Quiet time is diagnostic only; cancellation/deadline stop our process group."""
    process = None
    last_event = time.monotonic()
    start = last_event
    pending_tools = set()
    failed_turn = False
    usage = None
    thread_id = None
    buffer = ""
    terminal_reason = None
    termination_sent = False

    def stop_once():
        nonlocal termination_sent
        if process is not None and not termination_sent:
            termination_sent = True
            stop_owned_process(process)

    try:
        with (directory / "events.jsonl").open("w") as out, (directory / "stderr.log").open("w") as err:
            process = subprocess.Popen(command, env=env, stdout=out, stderr=err,
                                       stdin=subprocess.DEVNULL, start_new_session=True)
            state.update(status="running", pid=process.pid)
            with (directory / "events.jsonl").open() as events:
                while True:
                    buffer += events.read()
                    exited = process.poll() is not None
                    if exited:
                        buffer += events.read()
                        if buffer and not buffer.endswith("\n"):
                            buffer += "\n"
                    lines = buffer.split("\n")
                    buffer = lines.pop()
                    for line in lines:
                        try:
                            event = json.loads(line)
                        except (ValueError, TypeError):
                            continue
                        last_event = time.monotonic()
                        kind = event.get("type", "unknown")
                        state["last_event"] = kind
                        if kind == "thread.started":
                            thread_id = event.get("thread_id")
                        if kind in {"error", "turn.failed"}:
                            failed_turn = True
                        if kind == "turn.completed":
                            usage = event.get("usage")
                        item = event.get("item", {})
                        if item.get("type") in {"command_execution", "mcp_tool_call"}:
                            if kind == "item.started":
                                pending_tools.add(item.get("id"))
                            elif kind == "item.completed":
                                pending_tools.discard(item.get("id"))
                    now = time.monotonic()
                    state.update(elapsed_seconds=round(now-start, 1),
                                 quiet_seconds=round(now-last_event, 1),
                                 needs_attention=now-last_event >= quiet_seconds,
                                 phase="tool_running" if pending_tools else "awaiting_model_or_output",
                                 thread_id=thread_id, usage=usage,
                                 observed_failed_turn=failed_turn)
                    if (directory / "cancel.request").exists():
                        terminal_reason = "cancelled"
                    elif now-start >= max_seconds:
                        terminal_reason = "deadline_reached"
                    if exited:
                        if terminal_reason:
                            stop_once()
                        break
                    if terminal_reason:
                        stop_once()
                        continue
                    save_status(directory, state)
                    time.sleep(0.25)
        result = directory / "result.txt"
        has_result = result.exists() and bool(result.read_text().strip())
        state.update(exit_code=process.returncode,
                     status=terminal_reason or ("completed_unverified" if process.returncode == 0 and has_result and not failed_turn else "failed"))
    except KeyboardInterrupt:
        if process:
            stop_once()
        state.update(status="cancelled", reason="supervisor_interrupted")
    except Exception as exc:
        if process:
            stop_once()
        state.update(status="failed", reason=type(exc).__name__)
    finally:
        state["finished_at"] = time.time()
        state["phase"] = "finished"
        state["needs_attention"] = state["status"] != "completed_unverified"
        save_status(directory, state)
    return state


def run(args):
    cwd = Path(args.cwd).expanduser().resolve(strict=True)
    task = Path(args.task_file).expanduser().resolve(strict=True).read_text()
    if not cwd.is_dir() or not task.strip():
        raise ValueError("A working directory and nonempty task file are required")
    extra_dirs = [Path(p).expanduser().resolve() for p in getattr(args, 'add_dir', [])]
    if any(not p.is_dir() for p in extra_dirs):
        raise ValueError('--add-dir must name an existing directory')
    if args.role == 'review' and (extra_dirs or getattr(args, 'mcp_config', None)):
        raise ValueError('Review workers stay read-only and do not load additional mutable tools')
    contexts = []
    for source in getattr(args, 'context_file', []):
        source = Path(source).expanduser().resolve(strict=True)
        content = source.read_text()
        if sum(len(c) for _, c in contexts) + len(content) > 200000:
            raise ValueError('Context packet exceeds 200000 characters; select the relevant material')
        contexts.append((source, content))
    extra_mcp_text = ''
    extra_mcp_names = []
    if getattr(args, 'mcp_config', None):
        extra_mcp_text = Path(args.mcp_config).expanduser().resolve(strict=True).read_text()
        supplied = tomllib.loads(extra_mcp_text)
        if set(supplied) != {'mcp_servers'} or not isinstance(supplied['mcp_servers'], dict):
            raise ValueError('--mcp-config may contain only mcp_servers settings')
        if any(not isinstance(server, dict) for server in supplied['mcp_servers'].values()):
            raise ValueError('Each mcp_servers entry must be a table')
        if 'cua_repl' in supplied['mcp_servers']:
            raise ValueError('Use the native Computer Use configuration; do not override cua_repl')
        extra_mcp_names = [name for name, server in supplied['mcp_servers'].items()
                           if server.get('enabled', True)]
    computer_enabled = args.role == "execute" and not args.no_computer_use
    computer_config, computer_manifest = computer_use_config() if computer_enabled else ("", None)
    directory = Path(args.run_dir).expanduser().resolve()
    if directory == cwd or directory in cwd.parents:
        raise ValueError("Run directory cannot contain the working directory")
    directory.mkdir(parents=True, exist_ok=False)
    directory.chmod(0o700)
    home = directory / "home"
    home.mkdir()
    # Inherit visibility plus the selected desktop runtime, not unrelated MCPs or history.
    original_config = Path.home() / ".codex/config.toml"
    config = tomllib.loads(original_config.read_text()) if original_config.exists() else {}
    entries = config.get("skills", {}).get("config", [])
    visibility = "\n".join("[[skills.config]]\npath = " + json.dumps(x["path"]) +
                            "\nenabled = " + str(x.get("enabled", True)).lower()
                            for x in entries)
    (home / "config.toml").write_text(visibility + computer_config + "\n" + extra_mcp_text)
    (directory / "task.md").write_text(task)
    prompt = ("Complete only the attached bounded task. Read applicable project instructions. "
              "Limit reading to task-named files and their directly necessary dependencies; do not recursively search unrelated directories or historical runs. "
              "Preserve unrelated and concurrent changes. Do not read credentials. Change configuration only when explicitly within the attached task scope. "
              "Do not spawn other agents. Report actual evidence, failures, and unverified areas. ")
    if args.role == "review":
        prompt += "Review independently; do not edit source files. Check requirements and artifacts rather than trusting a completion summary. "
    if computer_enabled:
        prompt += ("Codex native Computer Use is available through cua_repl. Use it only for UI actions authorized by the task, and only in the task's target apps. "
                   "Follow its returned API documentation and app access controls. Do not substitute AppleScript or shell UI automation. "
                   "Verify UI outcomes from fresh accessibility state or screenshots. Report permission or tool failures rather than bypassing them. ")
    prompt += "\n\n" + task
    for index, (source, content) in enumerate(contexts):
        (directory / ('context-' + str(index) + '.md')).write_text(content)
        prompt += '\n\nAttached context from ' + str(source) + ':\n' + content
    prompt += ('\n\nReview filesystem access is read-only.' if args.role == 'review' else '\n\nWritable task directories: ' + ', '.join(str(p) for p in [cwd] + extra_dirs))

    launcher = Path(__file__).resolve().parent / "codex-go"
    overlay = json.loads((launcher.parent / "config-overrides.json").read_text())
    route = dict(x.split("=", 1) for x in overlay if x.startswith(("model=", "model_provider=")))
    expected_model = json.loads(route["model"])
    if json.loads(route["model_provider"]) != "opencode_go" or not expected_model.startswith("deepseek-"):
        raise ValueError("codex-go no longer selects the expected DeepSeek provider; inspect before running")
    command = [str(launcher), "-c", "agents.enabled=false",
               "-c", "sandbox_workspace_write.network_access=true", "exec", "--skip-git-repo-check",
               "--json", "-s", "read-only" if args.role == "review" else "workspace-write",
               "-C", str(cwd), "-o", str(directory / "result.txt"), "-"]
    for extra_dir in extra_dirs:
        command[-1:-1] = ['--add-dir', str(extra_dir)]
    # A prompt file keeps task content out of the process command line.
    (directory / "prompt.md").write_text(prompt)
    # exec accepts a prompt argument; use a short instruction to read our task packet.
    command[-1] = "Read " + str(directory / "prompt.md") + " and execute that task only."
    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    state = {"format": "deepseek-worker-v1", "run_id": str(uuid.uuid4()), "status": "starting",
             "title": getattr(args, "title", None),
             "messaging_enabled": False,
             "transport": "exec" if getattr(args, "legacy_exec", False) else "app-server",
             "task_group": getattr(args, "task_group", None) or os.environ.get("CODEX_THREAD_ID"),
             "parent_run_id": getattr(args, "parent_run_id", None),
             "goal": task[:500],
             "writable_roots": [str(p) for p in [cwd] + extra_dirs] if args.role == 'execute' else [],
             "context_sources": [str(p) for p, _ in contexts],
             "extra_mcp_servers": extra_mcp_names,
             "cwd": str(cwd), "role": args.role, "started_at": time.time(),
             "max_seconds": args.max_seconds, "quiet_warning_seconds": args.quiet_seconds,
             "computer_use_enabled": computer_enabled, "computer_use_manifest": computer_manifest,
             "result_path": str(directory / "result.txt"), "run_dir": str(directory)}
    save_status(directory, state)
    register_panel(directory, state)
    print(json.dumps({"run_dir": str(directory), "status": "starting"}), flush=True)
    if getattr(args, 'legacy_exec', False):
        state = supervise(command, directory, env, state, args.quiet_seconds, args.max_seconds)
    else:
        (directory / 'runtime.json').write_text(json.dumps({'launcher': str(launcher), 'model': expected_model}))
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import worker_runtime
        state = worker_runtime.supervise(directory, state)
        if state is None:
            raise ValueError('Another supervisor already owns this run')
    if state.get("thread_id"):
        for receipt in (home / "sessions").glob("**/*" + state["thread_id"] + "*.jsonl"):
            for line in receipt.open():
                record = json.loads(line)
                payload = record.get("payload", {})
                if record.get("type") == "session_meta":
                    state["actual_provider"] = payload.get("model_provider")
                elif record.get("type") == "turn_context":
                    state["actual_model"] = payload.get("model")
            break
    state["route_verified"] = state.get("actual_provider") == "opencode_go" and state.get("actual_model") == expected_model
    if state["status"] == "completed_unverified" and not state["route_verified"]:
        state.update(status="failed", reason="route_not_verified", needs_attention=True)
    if state.get("panel_registration_error"):
        register_panel(directory, state)
    save_status(directory, state)
    print(json.dumps(state, ensure_ascii=False), flush=True)
    return 0 if state["status"] == "completed_unverified" else 1


def register_panel(directory, state):
    try:
        panel_spec = importlib.util.spec_from_file_location("worker_panel", Path(__file__).resolve().with_name("worker-panel.py"))
        panel = importlib.util.module_from_spec(panel_spec)
        panel_spec.loader.exec_module(panel)
        panel.register(directory, state)
        state.pop("panel_registration_error", None)
    except (OSError, ValueError, ImportError) as exc:
        state["panel_registration_error"] = type(exc).__name__
        save_status(directory, state)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("run")
    p.add_argument("--cwd", required=True)
    p.add_argument("--task-file", required=True)
    p.add_argument("--run-dir", required=True, help="New directory for private receipts and isolated Codex home")
    p.add_argument("--add-dir", action="append", default=[], help="Additional task-owned writable directory (repeatable)")
    p.add_argument("--context-file", action="append", default=[], help="Snapshot required project rules or prior decisions (repeatable)")
    p.add_argument("--mcp-config", help="Task-selected MCP config TOML; only mcp_servers tables")
    p.add_argument("--role", choices=["execute", "review"], default="execute")
    p.add_argument("--legacy-exec", action="store_true", help="Compatibility execution without live feedback")
    p.add_argument("--task-group", help="Owning Codex task id for panel grouping")
    p.add_argument("--parent-run-id", help="Run being reviewed or continued")
    p.add_argument("--title", help="Short task label for the Codex side panel")
    p.add_argument("--no-computer-use", action="store_true", help="Explicit code-only run; reviews never expose UI mutation tools")
    p.add_argument("--quiet-seconds", type=float, default=300, help="No-event warning; does not kill the worker")
    p.add_argument("--max-seconds", type=float, default=1800, help="Explicit total runtime budget")
    for name in ["status", "cancel", "continue"]:
        p = sub.add_parser(name)
        p.add_argument("run_dir")
    p = sub.add_parser("panel", help="Start/reuse the local panel and print its URL")
    p.add_argument("--task-group", default=os.environ.get("CODEX_THREAD_ID"))
    p.add_argument("--add", action="append", default=[], help="Register an existing run directory")
    args = parser.parse_args()
    try:
        if args.action == "panel":
            command = [sys.executable, str(Path(__file__).resolve().with_name("worker-panel.py"))]
            if args.task_group:
                command.extend(["--task-group", args.task_group])
            for directory in args.add:
                command.extend(["--add", directory])
            return subprocess.call(command)
        if args.action == "run":
            if args.quiet_seconds <= 0 or args.max_seconds <= 0:
                raise ValueError("Time limits must be positive")
            return run(args)
        directory = Path(args.run_dir).expanduser().resolve(strict=True)
        state = read_status(directory)
        if args.action == "continue":
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import worker_runtime
            worker_runtime.supervise(directory, resume=True)
            return 0
        if args.action == "cancel" and state["status"] in RUNNING:
            (directory / "cancel.request").write_text("User requested cancellation\n")
            state["cancel_requested"] = True
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
