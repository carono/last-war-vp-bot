r"""One monitoring switch per sniffer, however many places it is drawn (task #1264, #1272).

The ghost switch is drawn TWICE, and it has to be: the page carrying it is called
«Призрак: карта», while the page a person looks under is called «Операция Призрак». The ★
one is drawn ONCE — on the ★ page, over the list it fills (#1272). It had a second copy
for a while, up on a frame called «Секретные задания», because moving it down had left
that frame standing with its old title and only the map sweep inside and the switch read
as gone; the frame and the sweep are both gone now, so the reassurance has nothing left
to reassure and the box lives with its list.

**The danger of drawing one twice is a second variable**, and it is not hypothetical: two
checkbuttons over one capture, each holding its own state, agree until the first time
anything else moves it — a capture that stops on its own, a config restored, a press from
the phone — and from then on one of them is lying with no way to tell which. Tk makes the
safe version free: every checkbutton bound to ONE variable moves together, whichever is
pressed.

That is what this file pins, by building the real tab and reading the widgets back:

  * every checkbutton carrying the ★ capture names the SAME variable — and there is one;
  * exactly two carry the ghost capture, and both name the same variable;
  * the two variables are still different ones from each other (#1251: two sniffers,
    two switches — neither drawn copy may quietly merge them);
  * and the tab holds no third `BooleanVar` for either.

Needs Tk and a display; it opens a hidden window and takes it down again.

    C:\Python312\python.exe tests\test_panel_secret_tasks_switches.py
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import fake_runtime  # noqa: E402

_SKIPPED: list = []


def _skip(why) -> None:
    _SKIPPED.append(str(why))
    print(f"  skip (no display: {why})")


def _boxes(widget, out=None) -> list:
    """Every ttk Checkbutton under ``widget``, whatever page it is on."""
    out = [] if out is None else out
    if widget.winfo_class() == "TCheckbutton":
        out.append(widget)
    for child in widget.winfo_children():
        _boxes(child, out)
    return out


def _built():
    """The real tab, built against a cold runtime. ``None`` where there is no display."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return None
    try:
        root = tk.Tk()
        root.withdraw()
    except Exception as exc:                            # noqa: BLE001
        _skip(exc)
        return None

    from panel.tabs.secret_tasks.tab import SecretTasksTab

    rt = fake_runtime.cold_runtime(root)
    rt.settings.register(SecretTasksTab.SETTINGS)
    frame = ttk.Frame(root)
    frame.pack(fill="both", expand=True)
    tab = SecretTasksTab(rt, frame)
    rt.tabs.add(tab)
    tab.build()                                  # `build()` never touches the game
    root.update_idletasks()
    return root, frame, tab


def _named(boxes, var) -> list:
    """The boxes bound to ``var`` — Tk answers with the variable's NAME, so compare that."""
    return [b for b in boxes if str(b.cget("variable")) == str(var)]


def test_the_star_switch_is_on_the_star_page_and_nowhere_else():
    """One box, on the page it fills (#1272) — and it is REACHABLE, which is the point.

    The count is pinned in both directions on purpose. Zero is the bug #1264 was opened
    for (a switch nobody can find reads as a switch that is gone); two is the copy that
    was there while a frame above needed something in it, and a copy is what invites a
    second variable the next time somebody edits one of the pair.
    """
    built = _built()
    if built is None:
        return
    root, frame, tab = built
    try:
        mine = _named(_boxes(frame), tab.monitor_var)
        assert len(mine) == 1, f"expected the ★ page and only it, got {len(mine)}"
        # Pressing it moves the state the capture reads, and there is only one.
        tab.monitor_var.set(True)
        assert all(b.getvar(str(b.cget("variable"))) for b in mine)
    finally:
        root.destroy()


def test_the_ghost_switch_is_one_variable_in_two_places():
    built = _built()
    if built is None:
        return
    root, frame, tab = built
    try:
        mine = _named(_boxes(frame), tab.ghost_map.monitor_var)
        assert len(mine) == 2, f"expected both ghost pages, got {len(mine)}"
        assert len({str(b.cget("variable")) for b in mine}) == 1, mine
    finally:
        root.destroy()


def test_the_two_sniffers_are_still_two_switches():
    """Drawing each of them twice must not have made them one (#1251)."""
    built = _built()
    if built is None:
        return
    root, frame, tab = built
    try:
        assert str(tab.monitor_var) != str(tab.ghost_map.monitor_var)
        boxes = _boxes(frame)
        assert not (set(_named(boxes, tab.monitor_var))
                    & set(_named(boxes, tab.ghost_map.monitor_var)))
    finally:
        root.destroy()


def test_no_third_variable_was_made_for_either_capture():
    """A copy would show up as a box bound to something neither capture reads."""
    built = _built()
    if built is None:
        return
    root, frame, tab = built
    try:
        known = {str(tab.monitor_var), str(tab.ghost_map.monitor_var)}
        # Every box carrying one of the monitoring LABELS must be on a known variable.
        words = {tab.t("secret.monitoring.stars"), tab.t("secret.monitoring.ghost")}
        for box in _boxes(frame):
            if str(box.cget("text")) in words:
                assert str(box.cget("variable")) in known, (
                    f"«{box.cget('text')}» is bound to a variable no capture reads")
    finally:
        root.destroy()


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as exc:                        # noqa: BLE001
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
        else:
            print(f"  ok   {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed"
          + (f" ({len(_SKIPPED)} skipped: no display)" if _SKIPPED else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
