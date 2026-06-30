# Wiring Codex Into the Signal Light

The signal light is agent-agnostic. Every state event carries an `--agent` tag, so
Codex drives the same light as Claude Code by calling:

```bash
vibesignal event --agent codex --state working --quiet
vibesignal event --agent codex --state blocked --quiet
```

`needs_input` is still accepted as an alias for `blocked`, so a v1 wrapper keeps
working.

The intended mapping mirrors the Claude Code side:

| Codex situation | State |
|-----------------|-------|
| A turn starts, Codex is working | `working` |
| Codex needs approval or input | `blocked` |
| A turn finishes and waits on you | `done` |

## Where to Hook In

Codex exposes a `notify` program in `~/.codex/config.toml`, and newer versions add
a hooks system. The `notify` program is called with a JSON argument when events
such as "turn complete" or "approval required" occur. Point it at a small wrapper
that maps the event to a `vibesignal` call.

Exact event names and the JSON shape vary by Codex version, so confirm them against
the Codex docs for your installed version (`codex --version`) before relying on the
mapping. The command form above is stable; only the event source differs.

A minimal wrapper (pseudocode, adjust the event keys to your Codex version):

```python
# codex-notify.py  (set as the notify program in ~/.codex/config.toml)
import json, subprocess, sys

event = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
kind = event.get("type", "")

state = "working"
if kind == "approval-requested":
    state = "blocked"
elif kind == "agent-turn-complete":
    state = "done"

subprocess.run([
    "vibesignal", "event", "--agent", "codex",
    "--state", state, "--session", event.get("session_id", "codex"),
])
```

## Per-Turn States via the Hooks System

Codex 0.130+ exposes a hooks system that fires on the same per-turn events Claude
Code uses, configured in `~/.codex/config.toml` or an isolated `~/.codex/hooks.json`.
Map `UserPromptSubmit` and `PostToolUse` to `working`, `PermissionRequest` to
`blocked`, and `Stop` to `done` for the same live states as the Claude side. Trust the
hooks once via `/hooks` in a Codex session. Use `--quiet` for Codex hooks: some hook
types parse stdout as JSON, so normal human-readable status text causes an invalid
hook output error.

The tracked snippet is [`codex-hooks.snippet.json`](codex-hooks.snippet.json). Merge it
into `~/.codex/hooks.json`. If `vibesignal` is not on the hook shell's `PATH`, replace
the command prefix with an absolute interpreter form such as
`C:/Users/<you>/miniforge3/envs/py312/python.exe -m vibesignal`.

Keep [`codex-notify.py`](codex-notify.py) as a completion-only fallback for older Codex
builds or for environments where the hooks system is disabled.

## SessionEnd Asymmetry

Claude Code fires a `SessionEnd` hook, so a closed Claude session calls
`vibesignal end --agent claude` and leaves the panel at once (see
`hooks/claude-settings.snippet.json`). Codex, as of 0.135, has no `SessionEnd` event,
so there is no matching `end` call for Codex. A closed Codex session is not cleared
explicitly. If the last recorded Codex state is `done`, it falls off the panel
through the 90s done fade; if it exits while `working`, after the 10-minute working
TTL; if it exits while `blocked` or `error`, it stays visible until the 8h backstop,
because Codex has no session-close event to clear it sooner. This asymmetry is
deliberate: add a Codex `end` hook only if a later Codex version gains a
session-close event.

This keeps the Claude Code and Codex paths on one light and one state store, which
satisfies the cross-agent requirement: the function works under role reversal or
when only one agent is present.
