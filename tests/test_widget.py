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
