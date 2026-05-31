from vibesignal import store


def test_record_and_load(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBECODING_SIGNAL_DIR", str(tmp_path))
    store.record("claude", "s1", "working", now=1000.0)
    active = store.load_active(ttl=600, now=1100.0)
    assert len(active) == 1
    assert active[0]["state"] == "working"
    assert active[0]["agent"] == "claude"


def test_ttl_drops_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBECODING_SIGNAL_DIR", str(tmp_path))
    store.record("claude", "s1", "working", now=1000.0)
    # 1000s later, past the 600s TTL
    assert store.load_active(ttl=600, now=2000.0) == []


def test_clear_one_session(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBECODING_SIGNAL_DIR", str(tmp_path))
    store.record("claude", "s1", "working", now=1000.0)
    store.record("codex", "s2", "needs_input", now=1000.0)
    store.clear(agent="claude", session="s1")
    active = store.load_active(ttl=600, now=1100.0)
    assert len(active) == 1
    assert active[0]["agent"] == "codex"


def test_clear_all(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBECODING_SIGNAL_DIR", str(tmp_path))
    store.record("claude", "s1", "working", now=1000.0)
    store.record("codex", "s2", "needs_input", now=1000.0)
    store.clear()
    assert store.load_active(ttl=600, now=1100.0) == []


def test_last_color_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBECODING_SIGNAL_DIR", str(tmp_path))
    assert store.get_last_color() is None
    store.set_last_color([255, 170, 0])
    assert store.get_last_color() == [255, 170, 0]
    store.set_last_color(None)
    assert store.get_last_color() is None


def test_session_id_with_path_separators_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBECODING_SIGNAL_DIR", str(tmp_path))
    store.record("claude", "a/b\\c", "working", now=1000.0)
    active = store.load_active(ttl=600, now=1100.0)
    assert len(active) == 1
    assert active[0]["session"] == "a/b\\c"


def test_distinct_sessions_do_not_collide(tmp_path, monkeypatch):
    # Regression: "a/b" and "a_b" both sanitize to "a_b" but must not share a file.
    monkeypatch.setenv("VIBECODING_SIGNAL_DIR", str(tmp_path))
    store.record("claude", "a/b", "working", now=1000.0)
    store.record("claude", "a_b", "needs_input", now=1000.0)
    active = store.load_active(ttl=600, now=1100.0)
    assert len(active) == 2
    assert {d["state"] for d in active} == {"working", "needs_input"}


def test_record_leaves_no_temp_files(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBECODING_SIGNAL_DIR", str(tmp_path))
    store.record("claude", "s1", "working", now=1000.0)
    sessions = tmp_path / "sessions"
    assert list(sessions.glob(".tmp-*")) == []
    assert len(list(sessions.glob("*.json"))) == 1


def test_clear_by_agent_only_keeps_other_agents(tmp_path, monkeypatch):
    # Regression: `clear --agent claude` must not wipe Codex's sessions.
    monkeypatch.setenv("VIBECODING_SIGNAL_DIR", str(tmp_path))
    store.record("claude", "s1", "working", now=1000.0)
    store.record("codex", "s2", "needs_input", now=1000.0)
    store.clear(agent="claude")
    active = store.load_active(ttl=600, now=1100.0)
    assert len(active) == 1
    assert active[0]["agent"] == "codex"


def test_clear_by_session_only_across_agents(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBECODING_SIGNAL_DIR", str(tmp_path))
    store.record("claude", "s1", "working", now=1000.0)
    store.record("codex", "s1", "needs_input", now=1000.0)
    store.record("claude", "s2", "working", now=1000.0)
    store.clear(session="s1")
    active = store.load_active(ttl=600, now=1100.0)
    assert len(active) == 1
    assert active[0]["session"] == "s2"


def _write_session_file(tmp_path, name, text):
    sessions = tmp_path / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / name).write_text(text, encoding="utf-8")


def test_load_active_skips_non_object_file(tmp_path, monkeypatch):
    # Regression: a valid-JSON but wrong-shape file must not raise in load_active.
    monkeypatch.setenv("VIBECODING_SIGNAL_DIR", str(tmp_path))
    _write_session_file(tmp_path, "bad.json", "[]")
    store.record("claude", "s1", "working", now=1000.0)
    active = store.load_active(ttl=600, now=1100.0)
    assert len(active) == 1
    assert active[0]["agent"] == "claude"


def test_load_active_skips_nonnumeric_ts(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBECODING_SIGNAL_DIR", str(tmp_path))
    _write_session_file(tmp_path, "badts.json",
                        '{"agent":"x","session":"y","state":"working","ts":"bad"}')
    store.record("claude", "s1", "working", now=1000.0)
    active = store.load_active(ttl=600, now=1100.0)
    assert len(active) == 1
    assert active[0]["agent"] == "claude"


def test_scoped_clear_tolerates_malformed_file(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBECODING_SIGNAL_DIR", str(tmp_path))
    _write_session_file(tmp_path, "bad.json", "[]")
    store.record("claude", "s1", "working", now=1000.0)
    store.clear(agent="claude")  # must not raise
    assert (tmp_path / "sessions" / "bad.json").exists()  # malformed file left in place
    assert store.load_active(ttl=600, now=1100.0) == []   # claude removed, bad skipped
