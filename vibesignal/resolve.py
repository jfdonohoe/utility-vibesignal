"""Resolve per-session states into light colors and panel rows, by priority."""

from __future__ import annotations

import time

from . import store


class State:
    WORKING = "working"
    BLOCKED = "blocked"
    DONE = "done"
    ERROR = "error"
    IDLE = "idle"
    NEEDS_INPUT = "needs_input"  # deprecated alias for BLOCKED


_ALIASES = {State.NEEDS_INPUT: State.BLOCKED}


def normalize(state: object) -> str:
    # Tolerate corrupt session files: a non-string state (e.g. a list from a
    # truncated or hand-edited file) must not crash resolution. _ALIASES.get on
    # an unhashable key would raise TypeError, so guard the type first.
    if not isinstance(state, str):
        return State.IDLE
    return _ALIASES.get(state, state)


# Higher index = higher priority when several sessions are active at once.
PRIORITY = [State.IDLE, State.WORKING, State.DONE, State.ERROR, State.BLOCKED]

# Solid RGB per state. None means "off".
COLORS: dict[str, list | None] = {
    State.WORKING: [0, 180, 255],  # blue
    State.BLOCKED: [255, 140, 0],  # amber (needs you now)
    State.DONE: [0, 250, 0],       # green
    State.ERROR: [255, 0, 0],      # red (manual failure, distinct from blocked)
    State.IDLE: None,              # off
}

# Each state has its own lifetime, because the hooks only refresh a session's
# timestamp when something happens. `working` refreshes on every tool call, so a
# working session silent past its TTL is treated as dead. `done` is a transient
# "your move" pulse that fades quickly. `blocked` and `error` are the opposite:
# nothing refreshes them while they wait on you, so a short TTL would make a
# long-pending prompt vanish exactly when it is most overdue. They persist for a
# long backstop instead, cleared sooner when you act (state changes), when
# SessionEnd fires, or by a manual clear; the backstop only self-cleans a
# hard-crashed session that left no final event.
#
# These TTLs are now a fallback, not the primary defense against orphaned
# sessions: store.process_alive() drops a session the moment its recorded
# pid is gone, so a closed terminal or killed process clears immediately
# instead of pinning the aggregate light for the rest of the TTL window.
WORKING_TTL_SECONDS = store.DEFAULT_TTL_SECONDS  # 600 (10 min): silent working is stale
DONE_TTL_SECONDS = 90.0                          # transient "your move" pulse
BLOCKED_TTL_SECONDS = 8 * 60 * 60.0              # 28800 (8 h): needs-you spans a workday

_STATE_TTL_SECONDS: dict[str, float] = {
    State.WORKING: WORKING_TTL_SECONDS,
    State.DONE: DONE_TTL_SECONDS,
    State.BLOCKED: BLOCKED_TTL_SECONDS,
    State.ERROR: BLOCKED_TTL_SECONDS,
}

# Load every file that could still be live under the longest per-state TTL, then
# let _expired apply the per-state rule. Loading only DEFAULT_TTL (the working
# TTL) would drop a long-blocked session before the resolver could keep it.
_LOAD_HORIZON_SECONDS = max(_STATE_TTL_SECONDS.values())


def _expired(state: str, ts: object, now: float) -> bool:
    """True if a state has outlived its lifetime and should drop off the panel."""
    ttl = _STATE_TTL_SECONDS.get(state, WORKING_TTL_SECONDS)
    age = now - ts if isinstance(ts, (int, float)) else 0.0
    return age > ttl


def aggregate(states: list[object]) -> str:
    best = State.IDLE
    best_rank = PRIORITY.index(State.IDLE)
    for s in states:
        s = normalize(s)
        if s not in PRIORITY:
            continue
        rank = PRIORITY.index(s)
        if rank > best_rank:
            best, best_rank = s, rank
    return best


def resolve_color(ttl: float = _LOAD_HORIZON_SECONDS,
                  now: float | None = None) -> tuple[str, list | None]:
    if now is None:
        now = time.time()
    states = []
    for d in store.load_active(ttl=ttl, now=now):
        st = normalize(d.get("state", State.IDLE))
        if _expired(st, d.get("ts", 0), now):
            continue
        if not store.process_alive(d.get("pid")):
            continue
        states.append(st)
    state = aggregate(states)
    return state, COLORS[state]


def resolve_per_session(ttl: float = _LOAD_HORIZON_SECONDS,
                        now: float | None = None) -> list[dict]:
    if now is None:
        now = time.time()
    rows = []
    for d in store.load_active(ttl=ttl, now=now):
        st = normalize(d.get("state", State.IDLE))
        if st not in COLORS:
            st = State.IDLE
        ts = d.get("ts", 0)
        if _expired(st, ts, now):
            continue
        if not store.process_alive(d.get("pid")):
            continue
        rows.append({
            "agent": d.get("agent", "?"),
            "project": d.get("project") or "?",
            "session": d.get("session", "?"),
            "state": st,
            "color": COLORS[st],
            "ts": ts,
        })
    # Highest priority first (blocked at top); within a state, oldest first.
    rows.sort(key=lambda r: (-PRIORITY.index(r["state"]), r["ts"]))
    return rows
