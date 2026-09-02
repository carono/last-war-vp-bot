"""Draw the picture an errand's card is (#2340), from the game's own sprite as reference.

The pictures on «Таймеры» used to be the client's own sprites — small stamps authored for
a corner of the UI and spread over a whole card, which is why a wash had to be laid over
them before words could be read on top. A CARD PICTURE is a different thing: composed for
the card, at card size, with room left for the text, so it can be shown at full brightness
and in full colour.

They are not the game's art and they are not text either, so neither tree they might have
gone into is right: the PROMPT is what this repository keeps (`tools/data/errand_art.json`)
and the picture is re-drawn per machine into ``results/errand_art/`` — git-ignored, like
every other picture here. A machine that never runs this has no covers and its cards draw
exactly as they did.

    python3 tools/generate_errand_art.py --errand collect_base_resources
    python3 tools/generate_errand_art.py --errand collect_base_resources --model <id>
    python3 tools/generate_errand_art.py --list

IT SPENDS REAL MONEY. One picture off the default model costs roughly a quarter of a
credit, so nothing is drawn without being named on the command line, an existing file is
kept unless ``--force`` says otherwise, and every run prints what it cost.

The key is `OPENROUTER_API_KEY` in the repository's git-ignored `.env`, and nowhere else
(`CLAUDE.md`); the client is `tools/lib/openrouter.py`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (str(_REPO / "tools" / "lib"), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import errand_icons                                          # noqa: E402
import openrouter as api                                     # noqa: E402

ART_SPEC = _REPO / "tools" / "data" / "errand_art.json"


def _spec() -> dict:
    return json.loads(ART_SPEC.read_text(encoding="utf-8"))


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 tools/generate_errand_art.py",
        description="Draw the card picture for one errand (costs credits).")
    parser.add_argument("--errand", default="", help="the errand name, e.g. collect_base_resources")
    parser.add_argument("--model", default="", help="override the model in errand_art.json")
    parser.add_argument("--force", action="store_true", help="redraw a picture that exists")
    parser.add_argument("--list", action="store_true", help="what has a prompt, and what is drawn")
    args = parser.parse_args(argv)

    spec = _spec()
    prompts = spec.get("prompts") or {}
    out_dir = Path(errand_icons.ART_ROOT)

    if args.list or not args.errand:
        for name in sorted(prompts):
            drawn = (out_dir / f"{name}.png").is_file()
            print(f"  {name:<28} {'drawn' if drawn else 'not drawn'}")
        if args.errand:
            return 0
        if not args.list:
            print("\nname one with --errand; a picture costs credits", file=sys.stderr)
            return 2
        return 0

    prompt = prompts.get(args.errand)
    if not prompt:
        print(f"no prompt for {args.errand!r} in {ART_SPEC}", file=sys.stderr)
        return 2
    target = out_dir / f"{args.errand}.png"
    if target.is_file() and not args.force:
        print(f"{target} already exists — pass --force to redraw it (it costs credits)")
        return 0

    # The sprite the card used to draw IS the reference: same colours, same materials, so
    # a cover does not look like it came from another game — UNLESS the spec names other
    # sprites, which is for the errands whose own icon does not depict the thing (the
    # truck errand wears the idle-reward clock).
    stems = list((spec.get("references") or {}).get(args.errand) or [])
    if not stems:
        stem = errand_icons.stem_for(args.errand)
        stems = [stem] if stem else []
    references = []
    for stem in stems:
        sprite = errand_icons.file_named(stem + ".png")
        if sprite:
            references.append(sprite)
        else:
            print(f"warning: no sprite {stem!r} on this machine", file=sys.stderr)
    if not references:
        print(f"warning: drawing {args.errand} without a reference (run "
              f"tools/extract_errand_icons.py first for a closer match)", file=sys.stderr)

    model = args.model or spec.get("model") or api.default_model()
    text = prompt + " " + str(spec.get("shared") or "")
    client = api.Client()
    answer = client.image(text, model=model, references=references)
    if not answer.images:
        print("the model sent no picture; it said: " + (answer.text or "(nothing)"),
              file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(answer.images[0])
    print(str(target))
    print(f"[{answer.model or model}] cost {answer.usage.cost:.6f} credits", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except api.NotConfigured as exc:
        print(f"not configured: {exc}", file=sys.stderr)
        raise SystemExit(3) from None
    except api.OpenRouterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
