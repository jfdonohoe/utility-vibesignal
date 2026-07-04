import pytest

from vibesignal import widget


def test_font_family_per_platform(monkeypatch):
    # Locks the Windows return value so a future helper edit cannot silently
    # swap Segoe UI for a generic family and degrade the widget's look there.
    monkeypatch.setattr("sys.platform", "win32")
    assert widget._font_family() == "Segoe UI"
    monkeypatch.setattr("sys.platform", "darwin")
    assert widget._font_family() == "Helvetica Neue"
    monkeypatch.setattr("sys.platform", "linux")
    assert widget._font_family() == "DejaVu Sans"


def test_glyph_idle_vs_active():
    assert widget.glyph("idle") == "○"
    assert widget.glyph("blocked") == "●"
    assert widget.glyph("working") == "●"
    assert widget.glyph("done") == "●"


def test_hex_covers_all_states():
    for s in ("blocked", "done", "working", "error", "idle"):
        assert s in widget.HEX


def test_row_fields_blocked():
    row = {"project": "aegis", "agent": "claude", "state": "blocked", "ts": 1000.0}
    g, project, agent, state, age = widget.row_fields(row, now=1072.0)
    assert g == "●"
    assert project == "aegis"
    assert agent == "claude"
    assert state == "blocked"
    assert age == "1m12s"


def test_row_fields_working_hides_age():
    row = {"project": "random", "agent": "codex", "state": "working", "ts": 1000.0}
    _g, _project, _agent, _state, age = widget.row_fields(row, now=1072.0)
    assert age == "—"  # em dash, not an age


def test_row_fields_truncates_long_project():
    row = {"project": "a-really-long-project-name", "agent": "claude",
           "state": "done", "ts": 1000.0}
    _g, project, _a, _s, _age = widget.row_fields(row, now=1000.0)
    assert len(project) <= 18


def test_widget_constructs_and_renders_one_tick(monkeypatch):
    # Guarded construction smoke test: skips on a headless box (no Tk display) and
    # otherwise checks that __init__'s one synchronous _tick renders a store row
    # without raising. destroy() cancels the pending after() callbacks, so nothing
    # schedules past the test.
    tk = pytest.importorskip("tkinter")
    from vibesignal import resolve
    row = {"agent": "claude", "project": "random", "session": "s1",
           "state": "blocked", "color": [220, 38, 38], "ts": 1000.0}
    monkeypatch.setattr(resolve, "resolve_per_session", lambda *a, **k: [row])
    monkeypatch.setattr(resolve, "resolve_color", lambda *a, **k: ("blocked", [220, 38, 38]))
    try:
        w = widget.Widget(interval_ms=10_000)
    except tk.TclError as exc:
        pytest.skip(f"no Tk display: {exc}")
    try:
        w.root.update_idletasks()
        # Prove the monkeypatched row rendered, not the "no active sessions"
        # placeholder (which also appends one cell): the row path emits the
        # project, agent, and state as separate labels. The accent-bar Frame has
        # no "text" option, so filter on widgets that carry one.
        texts = [c.cget("text") for c in w._cells if "text" in c.keys()]
        assert "random" in texts   # project
        assert "claude" in texts   # agent
        assert "blocked" in texts  # state
        # Whole-panel alarm: a blocked aggregate turns the frame red.
        assert str(w.root.cget("bg")) == "#dc2626"
    finally:
        w.root.destroy()


def test_keep_on_top_runs_each_tick(monkeypatch):
    # The macOS always-on-top fix hinges on re-asserting topmost every tick, so
    # lock in that _tick calls _keep_on_top (the synchronous first tick counts).
    tk = pytest.importorskip("tkinter")
    from vibesignal import resolve
    monkeypatch.setattr(resolve, "resolve_per_session", lambda *a, **k: [])
    monkeypatch.setattr(resolve, "resolve_color", lambda *a, **k: ("idle", None))
    calls = {"n": 0}
    monkeypatch.setattr(widget.Widget, "_keep_on_top",
                        lambda self: calls.__setitem__("n", calls["n"] + 1))
    try:
        w = widget.Widget(interval_ms=10_000)
    except tk.TclError as exc:
        pytest.skip(f"no Tk display: {exc}")
    try:
        assert calls["n"] >= 1
    finally:
        w.root.destroy()


def test_macos_float_level_silent_without_pyobjc(monkeypatch):
    # On a machine without the `macos` extra, the native level-raise must be a
    # no-op that never raises, so the stdlib -topmost path is the only effect.
    tk = pytest.importorskip("tkinter")
    from vibesignal import resolve
    monkeypatch.setattr(resolve, "resolve_per_session", lambda *a, **k: [])
    monkeypatch.setattr(resolve, "resolve_color", lambda *a, **k: ("idle", None))
    try:
        w = widget.Widget(interval_ms=10_000)
    except tk.TclError as exc:
        pytest.skip(f"no Tk display: {exc}")
    try:
        w._macos_float_level()  # must not raise regardless of pyobjc presence
    finally:
        w.root.destroy()


def test_keep_on_top_noop_off_darwin(monkeypatch):
    # Off macOS, _keep_on_top must return immediately without touching the native
    # float level -- no per-tick lift()/z-order churn on Windows/Linux, where the
    # startup -topmost already holds.
    tk = pytest.importorskip("tkinter")
    from vibesignal import resolve
    monkeypatch.setattr(resolve, "resolve_per_session", lambda *a, **k: [])
    monkeypatch.setattr(resolve, "resolve_color", lambda *a, **k: ("idle", None))
    try:
        w = widget.Widget(interval_ms=10_000)
    except tk.TclError as exc:
        pytest.skip(f"no Tk display: {exc}")
    try:
        monkeypatch.setattr("sys.platform", "linux")
        called = {"n": 0}
        monkeypatch.setattr(w, "_macos_float_level",
                            lambda: called.__setitem__("n", called["n"] + 1) or True)
        w._keep_on_top()
        assert called["n"] == 0
    finally:
        w.root.destroy()
