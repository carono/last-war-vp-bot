r"""Ask OpenRouter something from a terminal — and see what the answer cost.

    python -m tools.openrouter --models
    python -m tools.openrouter --models --search haiku --free
    python -m tools.openrouter --model <id> --prompt "Say hello in five words."
    python -m tools.openrouter --model <id> --prompt "Count to ten." --stream
    python -m tools.openrouter --model <id> --prompt "..." --json
    python -m tools.openrouter --key
    python -m tools.openrouter --model <id> --prompt "..." \
        --image results/art/card.png --reference results/errand_icons/some.png

The key is read from ``OPENROUTER_API_KEY`` — the environment first, then the
repository's git-ignored ``.env``. There is no default and no key in this file: with
none set the command says so and stops, rather than sending an empty ``Authorization``
header and reporting whatever 401 comes back.

The protocol this drives is written down in ``docs/research/openrouter-api.md``; the
client itself is ``tools/lib/openrouter.py``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
# tools/lib FIRST: this file is also called `openrouter`, and the library is what a
# bare import here must find.
for _p in (str(_REPO / "tools" / "lib"), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import openrouter as api                                     # noqa: E402


def _print_models(client: "api.Client", args: argparse.Namespace) -> int:
    models = client.models()
    needle = (args.search or "").lower()
    rows = []
    for model in models:
        model_id = str(model.get("id") or "")
        name = str(model.get("name") or "")
        pricing = model.get("pricing") or {}
        prompt_price = api._as_float(pricing.get("prompt"))
        completion_price = api._as_float(pricing.get("completion"))
        if needle and needle not in model_id.lower() and needle not in name.lower():
            continue
        if args.free and (prompt_price or completion_price):
            continue
        rows.append({
            "id": model_id,
            "name": name,
            "context_length": model.get("context_length"),
            "prompt_usd_per_token": prompt_price,
            "completion_usd_per_token": completion_price,
        })
    rows.sort(key=lambda r: (r["prompt_usd_per_token"], r["id"]))
    if args.limit > 0:
        rows = rows[:args.limit]
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    print(f"{len(rows)} model(s) of {len(models)}")
    for row in rows:
        # Prices are per token on the wire; per million is what a person compares.
        print(f"  {row['id']:<52} ctx {str(row['context_length'] or '?'):>9}"
              f"  in ${row['prompt_usd_per_token'] * 1e6:.3f}/M"
              f"  out ${row['completion_usd_per_token'] * 1e6:.3f}/M")
    return 0


def _print_key(client: "api.Client", args: argparse.Namespace) -> int:
    info = client.key_info()
    if args.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0
    limit = info.get("limit")
    remaining = info.get("limit_remaining")
    print(f"label            {info.get('label') or '(none)'}")
    print(f"credit limit     {'unlimited' if limit is None else limit}")
    print(f"limit remaining  {'unlimited' if remaining is None else remaining}")
    print(f"used (all time)  {info.get('usage')}")
    print(f"used (today)     {info.get('usage_daily')}")
    print(f"free tier        {info.get('is_free_tier')}")
    return 0


def _sampling(args: argparse.Namespace) -> dict:
    return {
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "top_p": args.top_p,
    }


def _chat(client: "api.Client", args: argparse.Namespace) -> int:
    model = args.model or api.default_model()
    if not model:
        print("no model: pass --model <id>, or set OPENROUTER_MODEL", file=sys.stderr)
        return 2
    prompt = args.prompt
    if prompt == "-":
        prompt = sys.stdin.read()
    if args.stream:
        return _chat_stream(client, args, model, prompt)
    answer = client.chat(prompt, model=model, system=args.system, **_sampling(args))
    if args.json:
        print(json.dumps(answer.as_dict(), indent=2, ensure_ascii=False))
        return 0
    print(answer.text, flush=True)      # before the usage line on stderr, so a
    if answer.tool_calls:               # terminal shows them in the order they happened
        print(f"\ntool calls: {json.dumps(answer.tool_calls, ensure_ascii=False)}")
    print(f"\n{_usage_line(answer.model or model, answer.provider, answer.usage)}",
          file=sys.stderr)
    return 0


def _chat_stream(client: "api.Client", args: argparse.Namespace,
                 model: str, prompt: str) -> int:
    pieces: list = []
    usage = api.Usage()
    for item in client.chat_stream(prompt, model=model, system=args.system,
                                   **_sampling(args)):
        if isinstance(item, api.Usage):
            usage = item
            continue
        pieces.append(item)
        if not args.json:
            sys.stdout.write(item)
            sys.stdout.flush()
    text = "".join(pieces)
    if args.json:
        print(json.dumps({"model": model, "text": text, "usage": usage.as_dict()},
                         indent=2, ensure_ascii=False))
        return 0
    print()
    print(f"\n{_usage_line(model, '', usage)}", file=sys.stderr)
    return 0


def _image(client: "api.Client", args: argparse.Namespace) -> int:
    """`--image out.png` — one picture, optionally drawn from references on disk."""
    model = args.model or api.default_model()
    if not model:
        print("no model: pass --model <id>, or set OPENROUTER_MODEL", file=sys.stderr)
        return 2
    prompt = sys.stdin.read() if args.prompt == "-" else args.prompt
    answer = client.image(prompt, model=model, references=args.reference,
                          system=args.system)
    if not answer.images:
        print("the model sent no picture; it said: " + (answer.text or "(nothing)"),
              file=sys.stderr)
        return 1
    out = Path(args.image)
    written = []
    for index, blob in enumerate(answer.images):
        # One picture keeps the name it was given; a model that sent several numbers
        # them rather than overwriting the first with the last.
        target = out if index == 0 else out.with_name(f"{out.stem}-{index + 1}{out.suffix}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        written.append(str(target))
    if args.json:
        print(json.dumps({"model": answer.model or model, "files": written,
                          "text": answer.text, "usage": answer.usage.as_dict()},
                         indent=2, ensure_ascii=False))
        return 0
    for path in written:
        print(path)
    if answer.text:
        print(answer.text)
    print(f"\n{_usage_line(answer.model or model, answer.provider, answer.usage)}",
          file=sys.stderr)
    return 0


def _usage_line(model: str, provider: str, usage: "api.Usage") -> str:
    where = f" via {provider}" if provider else ""
    return (f"[{model}{where}] {usage.prompt_tokens} in + {usage.completion_tokens} out"
            f" = {usage.total_tokens} tokens, cost {usage.cost:.6f} credits")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.openrouter",
        description="Talk to OpenRouter: list models, ask a model, see what it cost.")
    parser.add_argument("--model", default="", help="model id, e.g. vendor/model-name")
    parser.add_argument("--prompt", default="", help="the question ('-' reads stdin)")
    parser.add_argument("--system", default=None, help="optional system message")
    parser.add_argument("--stream", action="store_true", help="stream the answer")
    parser.add_argument("--models", action="store_true", help="list the models instead")
    parser.add_argument("--key", action="store_true",
                        help="show the key's credit limit and usage instead")
    parser.add_argument("--search", default="", help="with --models: filter by substring")
    parser.add_argument("--free", action="store_true",
                        help="with --models: only models priced at zero")
    parser.add_argument("--limit", type=int, default=40,
                        help="with --models: how many to print (0 = all)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--top-p", dest="top_p", type=float, default=None)
    parser.add_argument("--max-tokens", dest="max_tokens", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=api.DEFAULT_TIMEOUT,
                        help=f"seconds (default {api.DEFAULT_TIMEOUT:.0f})")
    parser.add_argument("--image", default="", help="ask for a PICTURE and write it here")
    parser.add_argument("--reference", action="append", default=[],
                        help="with --image: a picture on disk the model draws FROM "
                             "(repeatable)")
    parser.add_argument("--base-url", default=None,
                        help="override OPENROUTER_BASE_URL for this run")
    return parser


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = api.Client(base_url=args.base_url, timeout=args.timeout)
    try:
        if args.models:
            return _print_models(client, args)
        if args.key:
            return _print_key(client, args)
        if args.image:
            return _image(client, args)
        if not args.prompt:
            print("nothing to do: pass --prompt, or --models / --key", file=sys.stderr)
            return 2
        return _chat(client, args)
    except api.NotConfigured as exc:
        print(f"not configured: {exc}", file=sys.stderr)
        return 3
    except api.OpenRouterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
