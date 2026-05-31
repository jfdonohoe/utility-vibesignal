"""Thin wrapper over busylight-core.

This never raises into a hook. A missing light, a missing library, or a device
error degrades to a no-op so agent hooks never fail because of the signal light.
"""

from __future__ import annotations


def set_color(rgb: list | None) -> bool:
    """Set the light to a solid RGB color, or turn it off when rgb is None.

    Returns True if a light was driven, False if no light or library was available.
    """
    try:
        from busylight_core import Light
    except Exception:
        return False

    try:
        light = Light.first_light()
    except Exception:
        light = None
    if light is None:
        return False

    try:
        if rgb is None:
            light.off()
        else:
            light.on(tuple(rgb))
        return True
    except Exception:
        return False
    finally:
        # busylight-core defaults first_light(exclusive=True); release the handle
        # so the next short-lived hook process can acquire the device.
        _release(light)


def _release(light) -> None:
    release = getattr(light, "release", None)
    if callable(release):
        try:
            release()
        except Exception:
            pass
