"""Codex notify fallback for VibeSignal.

Run this script with the same Python interpreter that has VibeSignal installed,
then point Codex's `notify` setting at it. Modern Codex hooks are preferred;
this wrapper exists for older builds or as a completion-only fallback.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def _state_from_event(event_type: str) -> str:
    lowered = event_type.lower()
    if "approval" in lowered or "request" in lowered:
        return "blocked"
    if (
        "complete" in lowered
        or "finish" in lowered
        or "done" in lowered
        or "idle" in lowered
    ):
        return "done"
    return "working"


def main(argv: list[str]) -> int:
    try:
        payload = json.loads(argv[1]) if len(argv) > 1 else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    session = (
        payload.get("session_id")
        or payload.get("conversation_id")
        or payload.get("thread_id")
        or "codex"
    )
    cwd = payload.get("cwd") or payload.get("workdir") or payload.get("cwd_path") or ""
    cmd = [
        sys.executable,
        "-m",
        "vibesignal",
        "event",
        "--agent",
        "codex",
        "--state",
        _state_from_event(str(payload.get("type", ""))),
        "--session",
        str(session),
        "--quiet",
    ]
    if cwd:
        cmd += ["--project", os.path.basename(str(cwd).rstrip("/\\"))]

    try:
        subprocess.run(
            cmd,
            timeout=10,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
