"""One-click launcher and login-autostart helpers for the widget.

macOS: compiles a small AppleScript ``.app`` into ``~/Applications/`` via the
stock ``osacompile`` and writes a LaunchAgent plist that re-launches the widget
at login. Windows: writes ``.lnk`` shortcuts through the stock PowerShell
``WScript.Shell`` COM object -- Start Menu + Desktop for an on-demand launcher,
and the Startup folder for login autostart. Neither path adds a package
dependency; both shell out to tools that ship with the OS.

The widget command is pinned to the absolute interpreter of the env that runs
the install command, so a re-install from a freshly switched env re-pins
cleanly. On Windows the shortcut runs ``pythonw -m vibesignal widget`` so there
is no console window. Linux has no single conventional autostart target, so the
helpers refuse there; ``vibesignal widget &`` plus a ``~/.config/autostart/``
``.desktop`` entry is the documented path.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import xml.sax.saxutils
from pathlib import Path

LAUNCH_AGENT_LABEL = "io.github.yzhao062.vibesignal"
APP_NAME = "VibeSignal.app"
SHORTCUT_NAME = "VibeSignal.lnk"

# Console-script filenames pip can produce. POSIX wheels create a bare
# `vibesignal`; Windows wheels add a `.exe` launcher. Listing both keeps the
# resolver correct across platforms.
_SCRIPT_NAMES = ("vibesignal", "vibesignal.exe")


def _check_darwin() -> None:
    if sys.platform != "darwin":
        raise SystemExit(
            "vibesignal installer: only macOS is supported here; "
            f"current platform is {sys.platform!r}."
        )


def _check_supported() -> None:
    """Guard for non-macOS/non-Windows platforms (Linux, etc.)."""
    if sys.platform not in ("darwin", "win32"):
        raise SystemExit(
            "vibesignal installer: install-launcher / install-autostart support "
            f"macOS and Windows; current platform is {sys.platform!r}. On Linux, "
            "run `vibesignal widget &` and add a ~/.config/autostart/ .desktop entry."
        )


def vibesignal_args() -> list[str]:
    """Resolve the widget invocation as an absolute argv list.

    Prefers the actual invocation in this process so a manual
    ``python -m vibesignal install-autostart`` from a freshly switched
    env never pins back to a stale ``vibesignal`` from a prior env
    still on ``PATH``. ``shutil.which`` is deliberately not used.

    Order:

    1. ``sys.argv[0]`` when it is an existing executable file named
       ``vibesignal`` (POSIX) or ``vibesignal.exe`` (Windows pip wheel
       launcher) -- this is how an installed console script invokes itself;
       the path is absolute and matches the env it lives in.
    2. ``<sys.executable parent>/vibesignal`` or ``vibesignal.exe`` when
       present -- handles ``python -m vibesignal ...``: the sibling script of
       the running interpreter is the one pinned to this env.
    3. Module form ``[sys.executable, "-m", "vibesignal"]`` as a last
       resort, for editable installs that have not exposed the console
       script yet.
    """
    argv0_str = sys.argv[0] if sys.argv else ""
    if argv0_str:
        argv0 = Path(argv0_str).resolve()
        if (
            argv0.name in _SCRIPT_NAMES
            and argv0.is_file()
            and os.access(argv0, os.X_OK)
        ):
            return [str(argv0)]
    bin_dir = Path(sys.executable).resolve().parent
    for name in _SCRIPT_NAMES:
        sibling = bin_dir / name
        if sibling.is_file() and os.access(sibling, os.X_OK):
            return [str(sibling)]
    return [str(Path(sys.executable).resolve()), "-m", "vibesignal"]


# --------------------------------------------------------------------------- #
# macOS: AppleScript .app launcher + LaunchAgent autostart
# --------------------------------------------------------------------------- #

def _user_applications_dir() -> Path:
    return Path.home() / "Applications"


def _launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _plist_path() -> Path:
    return _launch_agents_dir() / f"{LAUNCH_AGENT_LABEL}.plist"


def _launchd_target() -> str:
    return f"gui/{os.getuid()}"


def applescript_source(args: list[str]) -> str:
    """Render the AppleScript that launches the widget headlessly.

    Backgrounded with ``&`` so the shell call returns at once; the widget
    process detaches and stays alive in the Aqua session. AppleScript string
    literals only need ``\\`` and ``"`` escaped, which is what the body does.
    """
    cmd = " ".join(shlex.quote(a) for a in [*args, "widget"])
    escaped = cmd.replace("\\", "\\\\").replace('"', '\\"')
    return f'do shell script "{escaped} > /dev/null 2>&1 &"\n'


def plist_content(args: list[str]) -> str:
    """Render the LaunchAgent plist as a UTF-8 XML string."""
    parts = [*args, "widget"]
    args_xml = "\n".join(
        f"        <string>{xml.sax.saxutils.escape(p)}</string>" for p in parts
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "    <key>Label</key>\n"
        f"    <string>{LAUNCH_AGENT_LABEL}</string>\n"
        "    <key>ProgramArguments</key>\n"
        "    <array>\n"
        f"{args_xml}\n"
        "    </array>\n"
        "    <key>RunAtLoad</key>\n"
        "    <true/>\n"
        "    <key>KeepAlive</key>\n"
        "    <false/>\n"
        "    <key>ProcessType</key>\n"
        "    <string>Interactive</string>\n"
        "    <key>StandardOutPath</key>\n"
        f"    <string>/tmp/{LAUNCH_AGENT_LABEL}.log</string>\n"
        "    <key>StandardErrorPath</key>\n"
        f"    <string>/tmp/{LAUNCH_AGENT_LABEL}.err</string>\n"
        "</dict>\n"
        "</plist>\n"
    )


def _macos_install_launcher() -> Path:
    args = vibesignal_args()
    src = applescript_source(args)

    dest_dir = _user_applications_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / APP_NAME

    if dest.exists():
        shutil.rmtree(dest)

    # Write AppleScript to a temp file so osacompile reads from disk; the
    # alternative `-e <source>` would inline a large string into argv, which
    # is fine for short scripts but loses on robustness around quoting.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".applescript", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(src)
        src_path = fh.name
    try:
        subprocess.run(["osacompile", "-o", str(dest), src_path], check=True)
    finally:
        Path(src_path).unlink(missing_ok=True)
    return dest


def _macos_uninstall_launcher() -> bool:
    dest = _user_applications_dir() / APP_NAME
    if not dest.exists():
        return False
    shutil.rmtree(dest)
    return True


def _macos_install_autostart(launch_now: bool = True) -> Path:
    args = vibesignal_args()
    content = plist_content(args)

    agents = _launch_agents_dir()
    agents.mkdir(parents=True, exist_ok=True)
    plist = _plist_path()
    target = _launchd_target()

    if plist.exists():
        # `bootout` is idempotent: an already-unloaded label produces a
        # non-zero exit that we deliberately swallow.
        subprocess.run(
            ["launchctl", "bootout", target, str(plist)],
            check=False,
            capture_output=True,
        )

    plist.write_text(content, encoding="utf-8")
    if launch_now:
        # `bootstrap` loads the agent into the running GUI session, and RunAtLoad
        # starts the widget immediately. Skipped when launch_now is False: the
        # plist in ~/Library/LaunchAgents is still loaded by launchd at the next
        # login, so login autostart works without spawning a widget right now.
        subprocess.run(
            ["launchctl", "bootstrap", target, str(plist)],
            check=True,
        )
    return plist


def _macos_uninstall_autostart() -> bool:
    plist = _plist_path()
    if not plist.exists():
        return False
    target = _launchd_target()
    subprocess.run(
        ["launchctl", "bootout", target, str(plist)],
        check=False,
        capture_output=True,
    )
    plist.unlink()
    return True


# --------------------------------------------------------------------------- #
# Windows: .lnk shortcuts via the stock PowerShell WScript.Shell COM object.
# The widget runs `pythonw -m vibesignal widget` so there is no console window.
# [Environment]::GetFolderPath resolves Startup / Programs / Desktop correctly
# even when the Desktop is redirected into OneDrive.
# --------------------------------------------------------------------------- #

def _windows_pythonw() -> str:
    """pythonw.exe (no console window) for the widget shortcut.

    pythonw is the sibling of the running interpreter; falls back to the plain
    executable if pythonw is missing (the widget still runs, with a brief
    console flash).
    """
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        return str(exe)
    pyw = exe.with_name("pythonw.exe")
    return str(pyw if pyw.is_file() else exe)


def _ps_squote(value: str) -> str:
    """Quote a string as a PowerShell single-quoted literal (doubling any quote)."""
    return "'" + value.replace("'", "''") + "'"


def _windows_shortcut_ps1(folder_id: str, target: str, arguments: str, workdir: str) -> str:
    """PowerShell that writes (overwriting) VibeSignal.lnk into a known folder.

    ``folder_id`` is a ``System.Environment.SpecialFolder`` name -- ``Startup``,
    ``Programs``, or ``Desktop``. The script prints the resolved .lnk path.
    """
    return (
        "$ErrorActionPreference = 'Stop'\n"
        f"$dir = [Environment]::GetFolderPath({_ps_squote(folder_id)})\n"
        f"$lnk = Join-Path $dir {_ps_squote(SHORTCUT_NAME)}\n"
        "$sh = New-Object -ComObject WScript.Shell\n"
        "$s = $sh.CreateShortcut($lnk)\n"
        f"$s.TargetPath = {_ps_squote(target)}\n"
        f"$s.Arguments = {_ps_squote(arguments)}\n"
        f"$s.WorkingDirectory = {_ps_squote(workdir)}\n"
        "$s.Description = 'VibeSignal status widget'\n"
        "$s.Save()\n"
        "Write-Output $lnk\n"
    )


def _windows_remove_ps1(folder_id: str) -> str:
    """PowerShell that removes VibeSignal.lnk from a known folder.

    Prints ``removed`` if a shortcut was deleted, ``absent`` otherwise.
    """
    return (
        "$ErrorActionPreference = 'Stop'\n"
        f"$dir = [Environment]::GetFolderPath({_ps_squote(folder_id)})\n"
        f"$lnk = Join-Path $dir {_ps_squote(SHORTCUT_NAME)}\n"
        "if (Test-Path -LiteralPath $lnk) { Remove-Item -LiteralPath $lnk -Force; "
        "Write-Output 'removed' } else { Write-Output 'absent' }\n"
    )


def _run_powershell(script: str) -> str:
    """Run a PowerShell script from a temp file; return its trimmed stdout."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ps1", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(script)
        path = fh.name
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    finally:
        Path(path).unlink(missing_ok=True)


def _windows_launch_widget() -> None:
    """Start the widget now, detached and console-less, mirroring macOS RunAtLoad."""
    creationflags = getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        [_windows_pythonw(), "-m", "vibesignal", "widget"],
        creationflags=creationflags,
        close_fds=True,
    )


def _windows_install_launcher() -> Path:
    """Create on-demand VibeSignal shortcuts in the Start Menu and on the Desktop.

    The Start Menu copy is searchable (type ``VibeSignal`` in the Start menu);
    the Desktop copy is one double-click away. Returns the Start Menu .lnk path.
    """
    target, args, workdir = _windows_pythonw(), "-m vibesignal widget", str(Path.home())
    programs = Path(
        _run_powershell(_windows_shortcut_ps1("Programs", target, args, workdir))
    )
    _run_powershell(_windows_shortcut_ps1("Desktop", target, args, workdir))
    return programs


def _windows_uninstall_launcher() -> bool:
    """Remove the Start Menu and Desktop shortcuts. True iff one was removed."""
    results = (
        _run_powershell(_windows_remove_ps1("Programs")),
        _run_powershell(_windows_remove_ps1("Desktop")),
    )
    return "removed" in results


def _windows_install_autostart(launch_now: bool = True) -> Path:
    """Write a Startup-folder shortcut so the widget launches at every login.
    Also starts the widget now unless ``launch_now`` is False. Returns the .lnk path."""
    target, args, workdir = _windows_pythonw(), "-m vibesignal widget", str(Path.home())
    lnk = Path(_run_powershell(_windows_shortcut_ps1("Startup", target, args, workdir)))
    if launch_now:
        _windows_launch_widget()
    return lnk


def _windows_uninstall_autostart() -> bool:
    """Remove the Startup-folder shortcut. True iff it was removed."""
    return _run_powershell(_windows_remove_ps1("Startup")) == "removed"


# --------------------------------------------------------------------------- #
# Public API: dispatch by platform.
# --------------------------------------------------------------------------- #

def install_launcher() -> Path:
    """Install a one-click launcher (macOS .app, or Windows Start Menu + Desktop
    shortcuts). Returns the launcher path. Re-install overwrites the prior one."""
    if sys.platform == "win32":
        return _windows_install_launcher()
    _check_supported()
    return _macos_install_launcher()


def uninstall_launcher() -> bool:
    """Remove the one-click launcher. Returns True iff something was removed."""
    if sys.platform == "win32":
        return _windows_uninstall_launcher()
    _check_supported()
    return _macos_uninstall_launcher()


def install_autostart(launch_now: bool = True) -> Path:
    """Install login autostart (macOS LaunchAgent, or a Windows Startup shortcut).
    Also starts the widget now unless ``launch_now`` is False. Returns the
    autostart file path."""
    if sys.platform == "win32":
        return _windows_install_autostart(launch_now=launch_now)
    _check_supported()
    return _macos_install_autostart(launch_now=launch_now)


def uninstall_autostart() -> bool:
    """Remove login autostart. Returns True iff something was removed."""
    if sys.platform == "win32":
        return _windows_uninstall_autostart()
    _check_supported()
    return _macos_uninstall_autostart()
