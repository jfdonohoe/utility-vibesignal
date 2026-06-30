import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _claude_snippet():
    return json.loads(
        (PROJECT_ROOT / "hooks" / "claude-settings.snippet.json").read_text(encoding="utf-8")
    )


def _codex_snippet():
    return json.loads(
        (PROJECT_ROOT / "hooks" / "codex-hooks.snippet.json").read_text(encoding="utf-8")
    )


def _commands(tree):
    found = []
    if isinstance(tree, dict):
        if isinstance(tree.get("command"), str):
            found.append(tree["command"])
        for value in tree.values():
            found.extend(_commands(value))
    elif isinstance(tree, list):
        for item in tree:
            found.extend(_commands(item))
    return found


def test_claude_snippet_notification_splits_blocked_and_done():
    # A real permission prompt is blocked; an idle prompt (turn ended, waiting on
    # you) is done. The old flat "Notification -> blocked" caused false blocked.
    notif = _claude_snippet()["hooks"]["Notification"]
    by_matcher = {e.get("matcher"): json.dumps(e["hooks"]) for e in notif}
    assert "blocked" in by_matcher["permission_prompt"]
    assert "done" not in by_matcher["permission_prompt"]
    assert "done" in by_matcher["idle_prompt"]
    assert "blocked" not in by_matcher["idle_prompt"]


def test_claude_snippet_stop_and_stopfailure_are_done():
    hooks = _claude_snippet()["hooks"]
    stop = json.dumps(hooks["Stop"])
    assert "done" in stop and "blocked" not in stop
    # A turn that ends on an API error is no longer working -> done.
    assert "done" in json.dumps(hooks["StopFailure"])


def test_claude_snippet_sessionend_clears_session():
    # SessionEnd must call `end` (not `event`) so a closed session leaves at once.
    sessionend = json.dumps(_claude_snippet()["hooks"]["SessionEnd"])
    assert "vibesignal end" in sessionend


def test_hook_snippets_use_quiet_vibesignal_commands():
    for snippet in (_claude_snippet(), _codex_snippet()):
        commands = _commands(snippet)
        assert commands
        for command in commands:
            assert "vibesignal" in command
            assert "signal_light" not in command
            assert "--quiet" in command


def test_codex_snippet_maps_turn_states():
    hooks = _codex_snippet()["hooks"]
    assert "working" in json.dumps(hooks["UserPromptSubmit"])
    assert "working" in json.dumps(hooks["PostToolUse"])
    assert "blocked" in json.dumps(hooks["PermissionRequest"])
    assert "done" in json.dumps(hooks["Stop"])


def test_codex_notify_fallback_uses_quiet_vibesignal():
    text = (PROJECT_ROOT / "hooks" / "codex-notify.py").read_text(encoding="utf-8")
    assert "signal_light" not in text
    assert '"vibesignal"' in text
    assert '"--quiet"' in text
    assert "stdout=subprocess.DEVNULL" in text
    assert "stderr=subprocess.DEVNULL" in text
