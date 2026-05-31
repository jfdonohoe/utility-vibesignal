"""macOS one-click launcher and LaunchAgent autostart helpers.

Generates a small AppleScript .app bundle in ``~/Applications/`` via the
stock ``osacompile`` (no new package dependency) and writes a LaunchAgent
plist that re-launches the widget at login. Both pin the absolute path of
the ``vibesignal`` script that owns this install, so a later
re-install from a different env can re-pin cleanly via the same commands.

macOS only by design. The helpers refuse on other platforms because their
guts (``osacompile``, ``launchctl bootstrap``, ``~/Library/LaunchAgents``)
do not have equivalents that translate one-for-one.
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

# Console-script filenames pip can produce. POSIX wheels create a bare
# `vibesignal`; Windows wheels add a `.exe` launcher. Listing both keeps the
# resolver correct even if `_check_darwin()` is later relaxed and the install
# commands grow Windows variants.
_SCRIPT_NAMES = ("vibesignal", "vibesignal.exe")


def _check_darwin() -> None:
    if sys.platform != "darwin":
        raise SystemExit(
            "vibesignal installer: only macOS is supported here; "
            f"current platform is {sys.platform!r}."
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


def install_launcher() -> Path:
    """Compile and install the one-click .app bundle to ``~/Applications/``.

    Returns the .app bundle path. Replaces any prior bundle at the same name
    so a re-install picks up a new vibesignal path.
    """
    _check_darwin()
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


def uninstall_launcher() -> bool:
    """Remove the .app bundle. Returns True iff something was removed."""
    _check_darwin()
    dest = _user_applications_dir() / APP_NAME
    if not dest.exists():
        return False
    shutil.rmtree(dest)
    return True


def install_autostart() -> Path:
    """Write the LaunchAgent plist and load it via ``launchctl bootstrap``.

    Idempotent: a prior load at the same label is booted out first so the new
    plist replaces it cleanly.
    """
    _check_darwin()
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
    subprocess.run(
        ["launchctl", "bootstrap", target, str(plist)],
        check=True,
    )
    return plist


def uninstall_autostart() -> bool:
    """Unload and delete the LaunchAgent plist. Returns True iff removed."""
    _check_darwin()
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
