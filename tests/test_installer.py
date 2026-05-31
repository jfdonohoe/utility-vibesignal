"""Unit tests for the macOS installer helpers.

Covers the pure-string helpers (AppleScript and plist generation) and the
darwin platform guard. The subprocess wrappers (`osacompile`, `launchctl
bootstrap`) are integration paths that depend on macOS system tools; those
are exercised manually via the CLI rather than in unit tests.
"""

import pytest

from vibesignal import installer


def test_check_darwin_refuses_non_darwin(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    with pytest.raises(SystemExit) as exc:
        installer._check_darwin()
    assert "linux" in str(exc.value)


def test_check_darwin_passes_on_darwin(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    installer._check_darwin()  # must not raise


def test_applescript_source_quotes_paths_with_spaces():
    src = installer.applescript_source(["/Users/jane doe/bin/vibesignal"])
    # shlex.quote wraps the path in single quotes, which AppleScript embeds
    # verbatim inside its own double-quoted string literal. The `widget` arg
    # is appended without quoting since it has no special characters.
    assert "'/Users/jane doe/bin/vibesignal'" in src
    assert "widget" in src
    assert src.endswith(' > /dev/null 2>&1 &"\n')


def test_applescript_source_escapes_double_quotes():
    # A path with a literal double quote (rare, but possible) must be escaped
    # so it does not terminate the AppleScript string early.
    src = installer.applescript_source(['/tmp/odd"name/vibesignal'])
    assert '\\"' in src


def test_applescript_source_uses_module_form_when_no_script():
    src = installer.applescript_source(["/abs/python", "-m", "vibesignal"])
    assert "/abs/python -m vibesignal widget" in src


def test_plist_content_has_required_keys():
    plist = installer.plist_content(["/usr/local/bin/vibesignal"])
    for key in ("Label", "ProgramArguments", "RunAtLoad", "KeepAlive",
                "ProcessType", "StandardOutPath", "StandardErrorPath"):
        assert f"<key>{key}</key>" in plist
    assert "<string>io.github.yzhao062.vibesignal</string>" in plist
    assert "<true/>" in plist   # RunAtLoad
    assert "<false/>" in plist  # KeepAlive


def test_plist_content_args_expand_correctly():
    # Console-script form: single ProgramArguments string + "widget".
    plist = installer.plist_content(["/usr/local/bin/vibesignal"])
    assert "<string>/usr/local/bin/vibesignal</string>" in plist
    assert "<string>widget</string>" in plist
    # Module form: three strings + "widget".
    plist2 = installer.plist_content(["/abs/python", "-m", "vibesignal"])
    assert "<string>/abs/python</string>" in plist2
    assert "<string>-m</string>" in plist2
    assert "<string>vibesignal</string>" in plist2
    assert "<string>widget</string>" in plist2


def test_plist_content_escapes_xml_special_chars():
    # An ampersand in a path would otherwise break the plist parser; the
    # rendering must XML-escape it.
    plist = installer.plist_content(["/tmp/a&b/vibesignal"])
    assert "<string>/tmp/a&amp;b/vibesignal</string>" in plist
    assert "/tmp/a&b/" not in plist  # raw ampersand must not appear


def test_vibesignal_args_falls_back_to_module_form(monkeypatch, tmp_path):
    # No argv0 hint and no sibling script -> module form. Point sys.executable
    # at an isolated tmp dir so we know there is no sibling vibesignal.
    fake_python = tmp_path / "python"
    fake_python.write_text("")
    monkeypatch.setattr("sys.argv", ["/some/path/__main__.py"])
    monkeypatch.setattr("sys.executable", str(fake_python))
    args = installer.vibesignal_args()
    assert args == [str(fake_python), "-m", "vibesignal"]


def test_vibesignal_args_uses_argv0_when_console_script(
    monkeypatch, tmp_path
):
    # When sys.argv[0] points at a real executable named vibesignal,
    # use it -- this is the installed-console-script invocation case.
    script = tmp_path / "vibesignal"
    script.write_text("#!/usr/bin/env python\n")
    script.chmod(0o755)
    monkeypatch.setattr("sys.argv", [str(script), "install-autostart"])
    args = installer.vibesignal_args()
    assert args == [str(script)]


def test_vibesignal_args_uses_sibling_in_python_module_form(
    monkeypatch, tmp_path
):
    # `python -m vibesignal install-autostart` from a specific env:
    # sys.argv[0] is __main__.py; sys.executable's sibling is the right
    # script for the env. Pinning to the sibling avoids a stale PATH match.
    env_bin = tmp_path / "env" / "bin"
    env_bin.mkdir(parents=True)
    fake_python = env_bin / "python"
    fake_python.write_text("")
    sibling = env_bin / "vibesignal"
    sibling.write_text("#!/usr/bin/env python\n")
    sibling.chmod(0o755)
    monkeypatch.setattr("sys.argv", ["/some/path/__main__.py"])
    monkeypatch.setattr("sys.executable", str(fake_python))
    args = installer.vibesignal_args()
    assert args == [str(sibling)]


def test_vibesignal_args_handles_windows_exe_argv0(monkeypatch, tmp_path):
    # On Windows, pip ships the console script as `vibesignal.exe`; sys.argv[0]
    # therefore carries the .exe suffix. The resolver must accept both forms so
    # a future relaxation of `_check_darwin()` does not regress Windows.
    script = tmp_path / "vibesignal.exe"
    script.write_text("")  # mock exe; content is irrelevant to path-based resolution
    script.chmod(0o755)
    monkeypatch.setattr("sys.argv", [str(script), "install-launcher"])
    args = installer.vibesignal_args()
    assert args == [str(script)]


def test_vibesignal_args_finds_exe_sibling(monkeypatch, tmp_path):
    # `python -m vibesignal ...` from a Windows env: sys.executable is
    # python.exe and the sibling launcher is vibesignal.exe (NOT bare
    # vibesignal). The resolver must prefer the .exe sibling over module form.
    env_bin = tmp_path / "Scripts"
    env_bin.mkdir(parents=True)
    fake_python = env_bin / "python.exe"
    fake_python.write_text("")
    sibling = env_bin / "vibesignal.exe"
    sibling.write_text("")
    sibling.chmod(0o755)
    monkeypatch.setattr("sys.argv", ["/some/path/__main__.py"])
    monkeypatch.setattr("sys.executable", str(fake_python))
    args = installer.vibesignal_args()
    assert args == [str(sibling)]


def test_vibesignal_args_ignores_stale_path_lookup(
    monkeypatch, tmp_path
):
    # The previous implementation called shutil.which, which would find an
    # older env's console script when run via `python -m vibesignal ...`.
    # The new resolver must NOT consult PATH; monkeypatching shutil.which to
    # a stale entry must not affect the result.
    env_bin = tmp_path / "current-env" / "bin"
    env_bin.mkdir(parents=True)
    fake_python = env_bin / "python"
    fake_python.write_text("")
    stale = tmp_path / "stale-env" / "bin" / "vibesignal"
    stale.parent.mkdir(parents=True)
    stale.write_text("#!/usr/bin/env python\n")
    stale.chmod(0o755)
    monkeypatch.setattr("sys.argv", ["/some/path/__main__.py"])
    monkeypatch.setattr("sys.executable", str(fake_python))
    monkeypatch.setattr("shutil.which", lambda name: str(stale))
    args = installer.vibesignal_args()
    # Must NOT pick the stale PATH script; should fall through to module form
    # because the sibling next to fake_python does not exist.
    assert args == [str(fake_python), "-m", "vibesignal"]
    assert str(stale) not in args
