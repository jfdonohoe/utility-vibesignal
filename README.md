# VibeSignal

A physical status light for coding agents. When Claude Code or Codex needs your
reply (a permission prompt or a question), a USB light on your desk turns amber;
when an agent finishes its turn, it turns blue. While an agent is working, it is
green. When nothing needs you, it is off. A light on the desk is harder to miss than another system
notification, which is the whole point.

This is the daemon-free, single-machine setup: one physical light driven directly
by agent hooks, plus a terminal `watch` panel and an always-on-top floating widget
for the times you run several sessions at once. It is built to grow into a
multi-agent strip or a networked setup later without rewiring the hooks.

## What It Does

| State | Light | Set by (Claude Code hooks) | Meaning |
|-------|-------|----------------------------|---------|
| `blocked` | Amber, solid | `Notification` (`permission_prompt`) | An agent needs you now (permission / question) |
| `done` | Blue, solid | `Stop`, `StopFailure`, `Notification` (`idle_prompt`) | An agent finished its turn; your move |
| `working` | Green, solid | `UserPromptSubmit`, `PostToolUse` | An agent is busy, do not interrupt |
| `error` | Red, solid | (manual only, see below) | A failure |
| `idle` | Off | TTL timeout, done-fade | Nothing needs you |

When several sessions run at once, the light shows the highest-priority state:
`blocked > error > done > working > idle`. If any one agent is waiting on you, the
light is amber, so the signal you care about most is never hidden.

## How It Works

No background service. Every hook invocation does the full cycle and exits:

```
hook fires  ->  vibesignal event --agent claude --state blocked
                  |
                  |-- write  ~/.vibesignal/sessions/claude-<id>.json = {state, ts}
                  |-- read   every session file, drop ones past their per-state TTL
                  |-- resolve the aggregate state by priority
                  |-- if the color changed since last time, set the USB light
```

Nothing has to stay running, so nothing can crash or need restarting. A session
that dies without a final event is dropped by its per-state TTL. A small `last_color.json`
cache means repeated same-state events (for example, many `PostToolUse` calls in
one turn) skip the USB write entirely and stay fast.

Concurrent hooks are kept honest two ways. The record-resolve-apply cycle runs
under a short cross-process lock, so two sessions firing at once cannot leave the
light on a lower-priority color (a finishing `working` hook overwriting a fresh
`blocked` event from another session). Every state file is written atomically (temp
file plus `os.replace`), so a reader never sees a half-written file. The lock is
bounded: if it cannot be taken quickly it proceeds anyway, because never blocking
the agent's hook matters more than perfect ordering under rare contention. The
color cache updates only after the device accepts the write, so testing with no
light attached does not suppress the first real write once the light is plugged in.

## Why Solid Colors, Not Blinking

Blinking a USB light needs a process that stays alive to drive the blink, which
would mean a daemon. Solid colors persist in the light hardware after the process
exits, so they fit the daemon-free design. This setup uses solid colors only. Amber solid
is still very visible. If you want a blinking "needs you" later, see Daemon Mode
below. This assumes a light that holds its last state, such as Luxafor, blink(1),
or BlinkStick. Kuando-style lights that need a constant connection would require
the daemon mode even for solid colors.

## Hardware

There is no purpose-built "AI agent light" product. The proven path is a
commercial presence light plus the open-source `busylight-core` library (the engine
behind `busylight-for-humans`), which supports many USB lights across multiple
vendors and is on PyPI.

Recommended for this single-beacon setup (both on Amazon US, both hold their
color, both supported by the library):

- **Luxafor Flag 2**: magnet-mounts on a monitor edge, USB-C, good eye-level spot.
- **blink(1) mk2**: tiny, fully open, a long-standing developer favorite.

Check the live price before buying.

## Install

```bash
pip install -e .
```

Run this from the `vibesignal/` directory. It installs the
`vibesignal` command and its `busylight-core` dependency (the engine behind
`busylight-for-humans`). On Windows,
USB HID access works once the library and its `hidapi` backend are installed by
pip.

## Wire Up Claude Code

Merge the keys in `hooks/claude-settings.snippet.json` into your
`~/.claude/settings.json` under `"hooks"` (user level, so every project drives the
one light). If a hook key already exists, append the new entry to its array rather
than replacing it. These keys (`UserPromptSubmit`, `PostToolUse`, `Notification`,
`Stop`, `StopFailure`, `SessionEnd`) do not collide with the shared `PreToolUse` and
`SessionStart` hooks. `Notification` is split by matcher: a `permission_prompt` sets
`blocked`, an `idle_prompt` sets `done`. `SessionEnd` calls `vibesignal end`,
so a closed session leaves the panel at once instead of waiting out the TTL.

The `vibesignal` command reads the session id from the hook's stdin JSON,
so one light tracks every concurrent session on the machine.

A note on `PostToolUse`: it returns the light to green after you approve a
mid-task permission prompt, at the cost of one quick call per tool use. Drop it if
you prefer zero per-tool overhead; the light then stays amber from a permission
prompt until the turn ends.

## Wire Up Codex

The state store is agent-agnostic: events carry an `--agent` tag. Codex points at
the same command with `--agent codex`, so one light covers both. See
`hooks/codex-hooks.md` for the mapping. Claude Code is wired first; the Codex side
is documented so a role-reversed or Codex-only session can wire it without
re-deriving the design.

## Test Without Hardware

The light arrives later than the code does, so the whole pipeline is observable
without a device:

```bash
vibesignal event --agent claude --state working
vibesignal status      # prints active sessions and the resolved color
vibesignal off         # clears all sessions
```

With no light connected, `event` records state and prints the color it would set,
then exits cleanly. Hooks never fail when the light is missing or unplugged.

## Watch Panel (Multiple Sessions)

Running several agents at once? A single light only says "someone needs you." The
panel shows which one. In a spare terminal pane:

```bash
vibesignal watch
```

It prints a live table, one row per active session, blocked rows first:

```
  PROJECT          AGENT    STATE      FOR
* aegis            claude   * blocked  1m12s
* agent-audit      codex    * blocked  8s
o iet-paper        claude   o done     3s
. random           claude   . working  --
```

The panel reads the same store the light uses, so it covers Claude and Codex
together and stays in sync with the light. It is a foreground viewer (Ctrl-C to
stop), not a daemon. `vibesignal watch --once` renders a single snapshot.

## Floating Widget (Always on Top)

The terminal panel needs a spare pane. The widget shows the same view as a small
always-on-top window, so it stays visible over any app:

```bash
# Windows (no console window)
pythonw -m vibesignal widget

# macOS one-click launcher: install once, then open via Spotlight / Dock
vibesignal install-launcher

# macOS / Linux on-demand from a terminal
vibesignal widget &
```

It starts in the bottom-left of the work area, shows one row per active session
(blocked first, with a state-colored accent bar), and refreshes about once a
second. Drag the header to move it anywhere on screen; right-click to quit.
On macOS, `Control`-click also opens the Quit menu, since some Tk builds report
the right mouse button as `Button-2`. The widget reads the same store as the light
and the panel, so all three stay in sync. A `done` row fades off after about 90
seconds, a silent `working` row clears after 10 minutes, and `blocked` or `error`
rows remain until the state changes or the 8-hour backstop expires.

The work area is detected per platform: `SPI_GETWORKAREA` on Windows (taskbar
excluded); `NSScreen.visibleFrame` on macOS (menu bar and Dock excluded), with a
28 / 80 px heuristic fallback when `pyobjc` is absent; full screen on Linux. The
heuristic assumes a bottom Dock, so a left or right Dock will overlap the widget
at startup. For accurate placement under any Dock orientation, install the macOS
extra: `pip install -e '.[macos]'` (pulls `pyobjc-framework-Cocoa`). The font is
`Segoe UI` on Windows, `Helvetica Neue` on macOS, and `DejaVu Sans` elsewhere.

### macOS One-Click Launcher and Autostart

Two helper subcommands set up the launcher and autostart without any new
package dependency; both compile down to standard macOS tooling (`osacompile`
for the .app, `launchctl bootstrap` for the LaunchAgent):

```bash
# One-click launcher: compiles an AppleScript .app to ~/Applications.
# Open via Spotlight ("VibeSignal"), or drag the .app to the Dock.
vibesignal install-launcher
vibesignal uninstall-launcher

# Login autostart: writes ~/Library/LaunchAgents/io.github.yzhao062.vibesignal.plist
# with the absolute path of vibesignal baked in (so LaunchAgent's empty
# PATH is not an issue), then loads it via `launchctl bootstrap gui/<uid>`.
# Widget starts immediately (RunAtLoad=true) AND at every future login; close
# any manually opened widget first to avoid duplicates. Re-run after switching
# env to re-pin.
vibesignal install-autostart
vibesignal uninstall-autostart
```

Both commands are macOS only and refuse on other platforms.

To autostart on Windows, place a shortcut to `pythonw -m vibesignal widget`
in the Startup folder. To autostart on Linux, add a `.desktop` autostart entry
under `~/.config/autostart/` that runs `vibesignal widget`.

## Status Taxonomy and Future Options

- **Blue split**: implemented in v2, refined in v3. `Notification` (`permission_prompt`)
  maps to `blocked` (amber); `Stop`, `StopFailure`, and `Notification` (`idle_prompt`)
  map to `done` (blue), so "blocked, look now" stays visually distinct from
  "finished, look when free."
- **Per-state lifetime**: a `done` row leaves the panel after about 90 seconds, and a
  silent `working` row after 10 minutes. A `blocked` row persists for up to 8 hours
  (cleared sooner when you act on it or the session ends), because nothing refreshes a
  blocked session while it waits, so a short TTL would drop it exactly when it is most
  overdue.
- **Red / error**: Claude Code has no clean "task failed" hook, so red remains
  manual only. Use `--state error` manually to test the red path.
- **Multi-agent strip**: a BlinkStick Strip with one cell per session needs only a
  session-to-cell map in `resolve.py`; the store already keys by session.
- **Daemon mode**: a small long-running process would enable blinking patterns and
  auto-off after idle, at the cost of a service to keep alive.

## Project Layout

```
vibesignal/
|-- README.md
|-- DESIGN.md
|-- LICENSE
|-- pyproject.toml
|-- vibesignal/
|   |-- __init__.py
|   |-- store.py        # per-session state files + TTL + atomic writes + last-color cache
|   |-- resolve.py      # aggregate + per-session resolution -> colors
|   |-- light.py        # busylight wrapper, no-ops without a device
|   |-- lock.py         # bounded cross-process lock for the event critical section
|   |-- panel.py        # live multi-session TUI panel (foreground viewer)
|   |-- widget.py       # always-on-top floating GUI panel (Tkinter, stdlib)
|   |-- installer.py    # macOS one-click .app + LaunchAgent autostart helpers
|   |-- __main__.py     # CLI invoked by hooks
|-- hooks/
|   |-- claude-settings.snippet.json
|   |-- codex-hooks.md
|-- tests/
    |-- test_resolve.py
    |-- test_store.py
    |-- test_lock.py
    |-- test_main.py
    |-- test_panel.py
    |-- test_widget.py
    |-- test_installer.py
    |-- test_hooks.py
```
