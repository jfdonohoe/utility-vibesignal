from vibesignal import lock


def test_file_lock_acquires(tmp_path):
    with lock.file_lock(tmp_path / "lock") as locked:
        assert locked is True


def test_file_lock_reacquires_after_release(tmp_path):
    p = tmp_path / "lock"
    with lock.file_lock(p) as first:
        assert first is True
    with lock.file_lock(p) as second:
        assert second is True


def test_file_lock_creates_parent(tmp_path):
    nested = tmp_path / "a" / "b" / "lock"
    with lock.file_lock(nested) as locked:
        assert locked is True
    assert nested.exists()
