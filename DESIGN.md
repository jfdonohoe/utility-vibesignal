# VibeSignal Design

Status: v1 single-beacon (commit `dbcb728`) and v2 multi-session panel (commit `cca7a37`) shipped. This document covers v1 through v3: the always-on-top floating widget, the done-fade, and the session-end clear.
Date: 2026-05-29

## Goal

Show, at a glance, which of several concurrent coding-agent sessions needs the user's attention. The user runs 4-5 Claude Code sessions (plus Codex) in the terminal at once; a single aggregate beacon ("an agent needs you") forces hunting across terminals. v2 adds a per-session view that names which session is blocked.

## Non-Goals

- Auto-detected red/error state: Claude Code has no clean "task failed" hook, so automatic error coloring is out (a noisy false signal is worse than none). `error` stays a manual, explicit state only.
- A background daemon for the light: the light is driven synchronously by hooks. The panel and the v3 widget are foreground viewers that only read the store; the widget autostarts on login and stays on top, but it never drives the light. No service drives the hardware.
- The physical multi-LED strip: out of this round, but the architecture leaves a clean seam for it (see Future Work).

## Architecture: One Store, Many Renderers

The design separates state from display. Hooks write per-session state to a file store; each display reads that store. Adding the panel does not change the hook layer or the light.

```
hooks (claude + codex)  -->  vibesignal event --agent X --state Y
        |
        v
   store  ~/.vibesignal/sessions/*.json     # source of truth: per-session, agent-tagged
        |
        |- resolve_color()        -> one color  -->  single light (light.py)       [v1 path, recolored]
        |- resolve_per_session()  -> rows                                          [v2, shared primitive]
                |
                |-->  panel:  `vibesignal watch`   (TUI table)              [v2]
                |-->  widget: `vibesignal widget`  (always-on-top GUI)      [v3]
                \-->  strip:  rows + session->cell map -> multi-LED                [future, reuses the primitive]
```

`resolve_per_session()` is the shared building block. The terminal panel renders it as table rows, the v3 floating widget renders it as an always-on-top GUI, and a future LED strip maps it to cells. Each renderer is additive over the same primitive, so no work is discarded. The single light keeps calling the same `resolve_color()` entry point; only its color map and priority gained the blue-split states.

## State Taxonomy (Blue-Split)

v1 mapped both `Notification` and `Stop` to one `needs_input` state. v2 split them so the user can tell "act now" from "your move", and v3 refined which hook sets which state:

| State | Color | Set by (Claude Code hook) | Meaning |
|-------|-------|---------------------------|---------|
| `working` | green | UserPromptSubmit, PostToolUse | running; leave alone |
| `blocked` | amber | Notification (`permission_prompt`) | needs you now (permission / question) |
| `done` | blue | Stop, StopFailure, Notification (`idle_prompt`) | finished the turn; your move |
| `error` | red | (manual only) | failure; not auto-detected |
| `idle` | grey / off | TTL timeout | nothing pending |

The `Notification` hook fires for more than one situation, so v3 splits it by matcher: a `permission_prompt` is `blocked` (act now), while an `idle_prompt` (the turn ended and is waiting on you) is `done`. A flat `Notification` to `blocked` produced false "blocked" on idle prompts, which is why the matcher split matters. `StopFailure` (a turn that ends on an API error) also maps to `done`: the turn is over, so the session is no longer working.

Single-light aggregate priority (highest wins across active sessions): `blocked > error > done > working > idle`. If any session is blocked, the one light is amber, so the most urgent signal is never hidden.

### Per-State Lifetime

Each state has its own lifetime on the panel, because the hooks only refresh a session's timestamp when something happens. `working` refreshes on every tool call, so a working session that goes silent for `WORKING_TTL_SECONDS` (10 min) is treated as dead. `done` is a transient "your move" pulse that fades after `DONE_TTL_SECONDS` (90 s). `blocked` and `error` are the opposite: nothing refreshes them while they wait on you, so a short TTL would make a long-pending prompt vanish exactly when it is most overdue. They persist for `BLOCKED_TTL_SECONDS` (8 h), long enough to span a workday, and clear sooner when you act (the state changes), when `SessionEnd` fires, or on a manual clear. The 8 h backstop only self-cleans a hard-crashed session that left no final event.

The per-state cutoff (`age > ttl`) is applied by `_expired` in both `resolve_color()` and `resolve_per_session()`, so the light and every renderer agree. The resolver loads every file within the longest TTL, then applies the per-state rule; a file is not deleted, it is filtered out of the views, matching the existing "stale files are ignored, not removed" policy.

Backward compatibility: `needs_input` is kept as an accepted alias for `blocked`, so a v1 hook snippet still works.

## Components

- `store.py`: unchanged. Already per-session, agent-tagged, atomic, TTL-bounded, malformed-file tolerant.
- `resolve.py`: `BLOCKED` and `DONE` states and their colors; `needs_input` maps to `blocked`; aggregate priority; `resolve_per_session(ttl)` returns rows `{agent, project, session, state, color, ts}`, sorted blocked-first; renderers compute display age from `ts`. v3 adds the per-state lifetime (`_STATE_TTL_SECONDS`, `_expired`): `working` 10 min, `done` 90 s, `blocked` and `error` an 8 h backstop, applied by both `resolve_color()` and `resolve_per_session()`.
- `panel.py`: `render(rows, now) -> str` formats rows into a colored table (testable without a terminal); `watch()` reads the store, calls `render`, reprints about once a second, and exits cleanly on Ctrl-C.
- `widget.py` (v3, new): an always-on-top Tkinter window (standard library only) that renders `resolve_per_session()` as a small floating panel, one row per session, blocked first. A third renderer over the same primitive, so it adds no hook-layer or store change. Borderless, drag by the header, right-click to quit, pinned bottom-left of the work area.
- `__main__.py`: `watch`, `widget`, and `end` subcommands; `event --state` choices include `blocked` and `done` (with `needs_input` as an alias). `end` clears one session by id from hook stdin, and no-ops when no id is present so it cannot wipe the `default` bucket.
- `light.py`: unchanged (still driven by the `resolve_color` color).
- `hooks/claude-settings.snippet.json`: the deployed model. UserPromptSubmit and PostToolUse to `working`; `Notification` split (`permission_prompt` to `blocked`, `idle_prompt` to `done`); `Stop` and `StopFailure` to `done`; `SessionEnd` to `end`.
- `hooks/codex-hooks.md`: the Codex side. The same per-turn mapping via the Codex hooks system, plus the `SessionEnd` asymmetry (Codex 0.135 has no session-close event, so a closed Codex session ages out by the per-state lifetime: `done` 90 s, `working` 10 min, `blocked` and `error` 8 h).

## Panel UX

`vibesignal watch` renders a live table in a spare terminal pane, one row per active session, blocked rows first:

```
  PROJECT          AGENT    STATE        FOR
* aegis            claude   * blocked    1m12s
* agent-audit      codex    * blocked    8s
o iet-paper        claude   o done       3s
. random           claude   . working    --
```

Refresh about once a second. ANSI color, standard library only (no new dependency), works in Windows Terminal and on macOS / Linux. It is a foreground viewer the user starts and stops; the light stays hook-driven.

## Error Handling

- The panel reuses the store's malformed-file tolerance (`_read_state_file`), so a corrupt session file does not crash the view.
- `watch` traps `KeyboardInterrupt` and restores the cursor and screen on exit.
- A missing or empty store renders an empty table, not an error.

## Testing

- `resolve_per_session()` — unit tests over fake store states: ordering (blocked first), color mapping, TTL filtering, multi-agent rows, and malformed-state tolerance.
- `render(rows, now)` — pure-function tests asserting the formatted output for representative states, including the ANSI color codes and blocked-first ordering (no terminal needed).
- Taxonomy and aggregate tests for the blocked/done split and the `needs_input` alias.

## Future Work: Physical Multi-LED Strip

When the user has a strip (for example a BlinkStick Strip, 8 LEDs), add a `session -> cell` mapping (recommended: an explicit per-terminal `VIBECODING_CELL`, with a project-based fallback) and a multi-LED driver in `light.py`. Both consume `resolve_per_session()` directly, so the strip is additive, not a rewrite.
