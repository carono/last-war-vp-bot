"""Smoke-test the configured providers and report the active profile.

Run:  python -m lastwar_bot [--profile <id>]
"""

from __future__ import annotations

import argparse
import sys

from .config import AppSettings
from .profile import DEFAULT_PROFILE_ID, Profile
from .providers import get_llm_provider
from .providers.base import LLMRequest


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test the bot's providers.")
    parser.add_argument(
        "--profile", default=DEFAULT_PROFILE_ID,
        help="Profile id to load (default: %(default)s). Stored in ./profiles/<id>.json.",
    )
    args = parser.parse_args()

    settings = AppSettings()
    profile = Profile.load(args.profile)
    print(f"Profile:         {profile.profile_id}  -> {profile.path}")
    print(f"  fields:        {list(profile.data) or '(empty)'}")
    print(f"LLM provider:    {settings.llm_provider}")
    print(f"Vision provider: {settings.vision_provider}")

    llm = get_llm_provider(settings)
    reply = llm.complete(LLMRequest(prompt="Reply with exactly: ok", max_tokens=8))
    print(f"LLM reply: {reply.strip()!r}")


if __name__ == "__main__":
    sys.exit(main() or 0)
