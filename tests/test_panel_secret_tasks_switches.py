r"""One monitoring switch, drawn in more than one place — and never copied (task #1264).

Both sniffer switches used to be reachable from exactly one page each, and the ★ one had
been moved off the frame it lived on for months. Live, that read as «галок мониторинга
нет»: the boxes were built, mapped and four hundred pixels down inside a five-page
notebook, and the frame still standing at the top with its old title held only the map
sweep. The ghost one was worse — the page carrying it is called «Призрак: карта», while
the page a person looks under is called «Операция Призрак».

So each switch is now drawn twice. **The danger of that is a second variable**, and it is
not hypothetical: two checkbuttons over one capture, each holding its own state, agree
until the first time anything else moves it — a capture that stops on its own, a config
restored, a press from the phone — and from then on one of them is lying with no way to
tell which. Tk makes the safe version free: every checkbutton bound to ONE variable moves
together, whichever is pressed.

That is what this file pins, by building the real tab and reading the widgets back:

  * exactly two checkbuttons carry the ★ capture, and both name the SAME variable;
  * exactly two carry the ghost capture, and both name the same variable;
  * the two variables are still different ones from each other (#1251: two sniffers,
    two switches — neither drawn copy may quietly merge them);
  * and the tab holds no third `BooleanVar` for either.

Needs Tk and a display; it opens a hidden window and takes it down again.

    C:\Python312\python.exe tests\test_panel_secret_tasks_switches.py
"""
from __future__ import annotations

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


def test_the_star_switch_is_one_variable_in_two_places():
    built = _built()
    if built is None:
        return
    root, frame, tab = built
    try:
        mine = _named(_boxes(frame), tab.monitor_var)
        assert len(mine) == 2, f"expected the frame and the ★ page, got {len(mine)}"
        # …and they are literally the same variable, not two spelled alike.
        assert len({str(b.cget("variable")) for b in mine}) == 1, mine
        # Pressing either moves both, because there is only one state to move.
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
