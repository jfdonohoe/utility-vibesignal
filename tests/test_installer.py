"""Unit tests for the installer helpers (macOS and Windows).

Covers the pure-string helpers (AppleScript and plist generation on macOS;
PowerShell shortcut-script generation on Windows), the platform guards, and
the platform dispatch of the public install/uninstall functions. The
subprocess wrappers (`osacompile`, `launchctl bootstrap`, and the PowerShell
`WScript.Shell` .lnk writes) are integration paths that depend on OS system
tools; those are exercised manually via the CLI rather than in unit tests.
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


# ----- Windows shortcut helpers (pure string + dispatch; .lnk creation is
# an integration path exercised via the CLI, like the macOS subprocess wrappers) -----

def test_ps_squote_wraps_and_doubles_quotes():
    assert installer._ps_squote("plain") == "'plain'"
    assert installer._ps_squote("a'b") == "'a''b'"


def test_windows_shortcut_ps1_has_folder_target_and_args():
    ps1 = installer._windows_shortcut_ps1(
        "Startup", r"C:\Py\pythonw.exe", "-m vibesignal widget", r"C:\Users\jane"
    )
    assert "GetFolderPath('Startup')" in ps1
    assert "CreateShortcut" in ps1
    assert r"$s.TargetPath = 'C:\Py\pythonw.exe'" in ps1
    assert "$s.Arguments = '-m vibesignal widget'" in ps1
    assert r"$s.WorkingDirectory = 'C:\Users\jane'" in ps1
    assert "VibeSignal.lnk" in ps1
    assert ps1.strip().endswith("Write-Output $lnk")


def test_windows_shortcut_ps1_escapes_single_quote_in_path():
    # A path with a single quote must be doubled so it cannot break the PS literal.
    ps1 = installer._windows_shortcut_ps1(
        "Desktop", r"C:\o'brien\pythonw.exe", "-m vibesignal widget", r"C:\o'brien"
    )
    assert "'C:\\o''brien\\pythonw.exe'" in ps1


def test_windows_remove_ps1_targets_named_shortcut():
    ps1 = installer._windows_remove_ps1("Programs")
    assert "GetFolderPath('Programs')" in ps1
    assert "VibeSignal.lnk" in ps1
    assert "Remove-Item" in ps1
    assert "'removed'" in ps1 and "'absent'" in ps1


def test_windows_pythonw_prefers_sibling_pythonw(monkeypatch, tmp_path):
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    py = scripts / "python.exe"
    py.write_text("")
    pyw = scripts / "pythonw.exe"
    pyw.write_text("")
    monkeypatch.setattr("sys.executable", str(py))
    assert installer._windows_pythonw() == str(pyw)


def test_windows_pythonw_falls_back_to_executable(monkeypatch, tmp_path):
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    py = scripts / "python.exe"
    py.write_text("")  # no pythonw.exe sibling
    monkeypatch.setattr("sys.executable", str(py))
    assert installer._windows_pythonw() == str(py)


def test_check_supported_refuses_linux(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    with pytest.raises(SystemExit) as exc:
        installer._check_supported()
    assert "linux" in str(exc.value)


def test_check_supported_passes_on_win32_and_darwin(monkeypatch):
    for plat in ("win32", "darwin"):
        monkeypatch.setattr("sys.platform", plat)
        installer._check_supported()  # must not raise


def test_install_launcher_dispatches_to_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    sentinel = object()
    monkeypatch.setattr(installer, "_windows_install_launcher", lambda: sentinel)
    assert installer.install_launcher() is sentinel


def test_install_autostart_dispatches_to_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    sentinel = object()
    monkeypatch.setattr(installer, "_windows_install_autostart", lambda launch_now=True: sentinel)
    assert installer.install_autostart() is sentinel


def test_uninstall_dispatches_to_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(installer, "_windows_uninstall_launcher", lambda: True)
    monkeypatch.setattr(installer, "_windows_uninstall_autostart", lambda: False)
    assert installer.uninstall_launcher() is True
    assert installer.uninstall_autostart() is False


# ----- install-autostart launch_now (so CI can install the entry headlessly,
# without spawning the GUI widget on a runner with no usable display) -----

def test_windows_autostart_launch_now_controls_widget_start(monkeypatch):
    # The Startup .lnk is always written (PowerShell mocked here); the widget is
    # only started when launch_now is True.
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(installer, "_run_powershell", lambda script: r"C:\Startup\VibeSignal.lnk")
    started = []
    monkeypatch.setattr(installer, "_windows_launch_widget", lambda: started.append(1))
    installer.install_autostart(launch_now=False)
    assert started == []        # --no-launch: widget not started
    installer.install_autostart(launch_now=True)
    assert started == [1]       # default: widget started now


def test_macos_autostart_launch_now_controls_bootstrap(monkeypatch, tmp_path):
    # The plist is always written; `launchctl bootstrap` (start now) only runs
    # when launch_now is True. Without it, login autostart still works because
    # launchd loads ~/Library/LaunchAgents at the next login.
    monkeypatch.setattr("sys.platform", "darwin")
    plist = tmp_path / "io.github.yzhao062.vibesignal.plist"
    monkeypatch.setattr(installer, "_launch_agents_dir", lambda: tmp_path)
    monkeypatch.setattr(installer, "_plist_path", lambda: plist)
    monkeypatch.setattr(installer, "_launchd_target", lambda: "gui/501")
    runs = []
    monkeypatch.setattr(installer.subprocess, "run", lambda cmd, **kw: runs.append(cmd))
    installer.install_autostart(launch_now=False)
    assert plist.exists()                                  # plist written
    assert not any("bootstrap" in cmd for cmd in runs)     # no start-now
    runs.clear()
    installer.install_autostart(launch_now=True)
    assert any("bootstrap" in cmd for cmd in runs)         # start-now
