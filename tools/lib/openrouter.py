r"""A small OpenRouter client — models, chat, streaming chat, and what it cost.

OpenRouter (``https://openrouter.ai``) is one HTTP door in front of many model
providers. It speaks the OpenAI Chat Completions dialect, so the wire is familiar:
``POST /api/v1/chat/completions`` with ``messages``, optionally ``stream: true``,
and a ``usage`` object on the way back that carries token counts **and the credits
the call actually cost**. What the protocol looks like, field by field, is written
down in ``docs/research/openrouter-api.md``; this module is the code side of it.

Nothing here needs a third-party package: it is ``urllib`` and ``json``, so it runs
under any interpreter this repository already uses.

    from openrouter import Client, NotConfigured

    client = Client()                                  # key from the environment
    answer = client.chat("Say hello in five words.", model="openai/gpt-4o-mini")
    print(answer.text, answer.usage.cost)

    for piece in client.chat_stream("Count to ten.", model="openai/gpt-4o-mini"):
        ...                                            # str deltas, then a Usage

**The key is never in the code.** It comes from ``OPENROUTER_API_KEY`` in the
environment, or from the repository's git-ignored ``.env`` — and when it is set
nowhere, every call raises :class:`NotConfigured` instead of going out with an empty
``Authorization`` header and coming back as an opaque 401. The address is
``OPENROUTER_BASE_URL`` in front of the published default, the same environment-first
shape ``tools/lib/game_paths.py`` uses for everything that differs per machine.

Errors are told apart rather than lumped together, because the four that matter want
four different reactions: :class:`AuthError` (401 — the key is wrong), :class:`OutOfCredit`
(402 — the account or the key's cap is empty), :class:`RateLimited` (429, carrying
``retry_after`` when the response named one) and :class:`ServerError` (5xx and 502/503
from a provider that is down — retry, possibly with another model).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

#: The published address of the API. Overridable per machine, never re-spelled at a
#: call site — the same rule every path in ``game_paths`` follows.
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

#: Seconds. Generous on purpose: a large model's first token can be a while coming,
#: and the streaming call reads for as long as the answer lasts.
DEFAULT_TIMEOUT = 120.0

_ENV_KEY = "OPENROUTER_API_KEY"
_ENV_BASE = "OPENROUTER_BASE_URL"
_ENV_MODEL = "OPENROUTER_MODEL"
_ENV_REFERER = "OPENROUTER_REFERER"
_ENV_TITLE = "OPENROUTER_TITLE"


# --------------------------------------------------------------------------- errors

class OpenRouterError(RuntimeError):
    """Anything that went wrong talking to OpenRouter."""

    def __init__(self, message: str, *, status: int | None = None,
                 code: str | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.body = body


class NotConfigured(OpenRouterError):
    """No API key anywhere — the call was never made."""


class AuthError(OpenRouterError):
    """401: the key is missing, disabled or not a key."""


class OutOfCredit(OpenRouterError):
    """402: the account balance or the key's own credit cap is exhausted."""


class Forbidden(OpenRouterError):
    """403: permissions, a guardrail, or a moderation block."""


class BadRequest(OpenRouterError):
    """400 (and other 4xx): the request itself is wrong."""


class RateLimited(OpenRouterError):
    """429: too many requests. ``retry_after`` is seconds, when the reply named one."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.retry_after = retry_after


class ServerError(OpenRouterError):
    """5xx: OpenRouter or the provider behind it failed. Worth retrying."""


class Timeout(OpenRouterError):
    """The request took longer than the timeout allowed."""


# ----------------------------------------------------------------------- the answers

@dataclass
class Usage:
    """What a call spent: tokens by the model's own tokenizer, and credits.

    ``cost`` is in OpenRouter credits (1 credit = 1 USD of account balance) and is
    what makes a run's price visible without a second request. The detail fields are
    absent on some providers and stay 0 there.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    upstream_cost: float = 0.0

    @classmethod
    def from_payload(cls, payload: Any) -> "Usage":
        if not isinstance(payload, dict):
            return cls()
        prompt_detail = payload.get("prompt_tokens_details") or {}
        completion_detail = payload.get("completion_tokens_details") or {}
        cost_detail = payload.get("cost_details") or {}
        return cls(
            prompt_tokens=_as_int(payload.get("prompt_tokens")),
            completion_tokens=_as_int(payload.get("completion_tokens")),
            total_tokens=_as_int(payload.get("total_tokens")),
            cost=_as_float(payload.get("cost")),
            reasoning_tokens=_as_int(completion_detail.get("reasoning_tokens")),
            cached_tokens=_as_int(prompt_detail.get("cached_tokens")),
            upstream_cost=_as_float(cost_detail.get("upstream_inference_cost")),
        )

    def as_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost": self.cost,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_tokens": self.cached_tokens,
            "upstream_cost": self.upstream_cost,
        }


@dataclass
class ChatAnswer:
    """One completed answer: the text, what the model asked to call, and the bill."""

    text: str = ""
    model: str = ""
    provider: str = ""
    finish_reason: str = ""
    tool_calls: list = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    id: str = ""
    raw: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "model": self.model,
            "provider": self.provider,
            "finish_reason": self.finish_reason,
            "text": self.text,
            "tool_calls": self.tool_calls,
            "usage": self.usage.as_dict(),
        }


# ------------------------------------------------------------------------ the config

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _dotenv_value(name: str) -> str:
    """Read one ``NAME=value`` out of the repository's git-ignored ``.env``.

    A deliberately tiny reader: no export lines, no interpolation, no quotes beyond a
    single surrounding pair. It exists so that a key lives in exactly one place on a
    machine, and never has to be exported by hand before a CLI run.
    """
    path = _repo_root() / ".env"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value.strip()
    return ""


def _setting(name: str, fallback: str = "") -> str:
    """Environment first, then ``.env``, then the fallback — and nothing hardcoded."""
    value = (os.environ.get(name) or "").strip()
    if value:
        return value
    value = _dotenv_value(name)
    return value if value else fallback


def api_key() -> str:
    """The key, or an empty string. Never a default: a key is nobody else's."""
    return _setting(_ENV_KEY)


def base_url() -> str:
    return _setting(_ENV_BASE, DEFAULT_BASE_URL).rstrip("/")


def default_model() -> str:
    """An optional per-machine default model id, from ``OPENROUTER_MODEL``."""
    return _setting(_ENV_MODEL)


#: Aliases, so that :class:`Client` can name its arguments ``api_key`` / ``base_url``
#: without hiding the module functions of the same name behind them.
_env_api_key = api_key
_env_base_url = base_url


# ------------------------------------------------------------------------ the client

class Client:
    """A thin, synchronous OpenRouter client.

    ``api_key`` / ``base_url`` are for tests and for a caller that has its own answer;
    left alone they come from the environment (then ``.env``), which is where a key
    belongs.
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 *, timeout: float = DEFAULT_TIMEOUT, referer: str | None = None,
                 title: str | None = None, opener: Any = None) -> None:
        self._key = (api_key if api_key is not None else _env_api_key()).strip()
        self._base = (base_url or _env_base_url()).rstrip("/")
        self._timeout = float(timeout)
        self._referer = referer if referer is not None else _setting(_ENV_REFERER)
        self._title = title if title is not None else _setting(_ENV_TITLE)
        self._opener = opener or urllib.request.urlopen

    # -- plumbing ----------------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def _headers(self, *, stream: bool = False) -> dict:
        if not self._key:
            raise NotConfigured(
                f"{_ENV_KEY} is not set — put it in the repository's .env "
                f"(git-ignored) or export it; no request was made")
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
        }
        # Optional attribution headers. OpenRouter uses them for its own rankings;
        # they are empty unless this machine chose to send one.
        if self._referer:
            headers["HTTP-Referer"] = self._referer
        if self._title:
            headers["X-OpenRouter-Title"] = self._title
        return headers

    def _request(self, method: str, path: str, payload: dict | None = None,
                 *, stream: bool = False, timeout: float | None = None):
        url = f"{self._base}/{path.lstrip('/')}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=data, method=method,
                                         headers=self._headers(stream=stream))
        try:
            return self._opener(request, timeout=timeout or self._timeout)
        except urllib.error.HTTPError as exc:                 # noqa: PERF203
            raise _from_http_error(exc) from None
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
                raise Timeout(f"OpenRouter did not answer in {timeout or self._timeout:.0f}s") from None
            raise OpenRouterError(f"cannot reach OpenRouter: {reason}") from None
        except TimeoutError:
            raise Timeout(f"OpenRouter did not answer in {timeout or self._timeout:.0f}s") from None

    def _get_json(self, path: str, *, timeout: float | None = None) -> dict:
        with self._request("GET", path, timeout=timeout) as response:
            return _read_json(response)

    # -- the endpoints -------------------------------------------------------------

    def models(self, *, timeout: float | None = None) -> list:
        """``GET /models`` — every model, with its pricing and its context length."""
        payload = self._get_json("/models", timeout=timeout)
        data = payload.get("data")
        return list(data) if isinstance(data, list) else []

    def key_info(self, *, timeout: float | None = None) -> dict:
        """``GET /key`` — the key's label, its credit cap and what is left of it."""
        payload = self._get_json("/key", timeout=timeout)
        data = payload.get("data")
        return dict(data) if isinstance(data, dict) else {}

    def chat(self, prompt: str | Sequence[dict], *, model: str,
             system: str | None = None, tools: Sequence[dict] | None = None,
             timeout: float | None = None, **params: Any) -> ChatAnswer:
        """``POST /chat/completions`` without streaming — one answer, with its bill.

        ``prompt`` is either a string (turned into one user message) or a ready list
        of messages. Extra sampling parameters (``temperature``, ``max_tokens``,
        ``top_p``, …) travel through ``**params`` untouched: OpenRouter omits what a
        caller did not send rather than substituting a default of its own.
        """
        payload = self._payload(prompt, model=model, system=system, tools=tools,
                                stream=False, params=params)
        with self._request("POST", "/chat/completions", payload, timeout=timeout) as response:
            body = _read_json(response)
        # A body can carry an error even under 200 — a provider that failed after the
        # status was committed reports it here rather than in the status.
        _raise_for_body(body)
        return _answer_from_body(body)

    def chat_stream(self, prompt: str | Sequence[dict], *, model: str,
                    system: str | None = None, tools: Sequence[dict] | None = None,
                    timeout: float | None = None, **params: Any) -> Iterator:
        """The same call with ``stream: true`` — yields text deltas, then a :class:`Usage`.

        The last thing yielded is the :class:`Usage` for the whole call (OpenRouter
        puts it on the final SSE message), so a caller that wants only the words can
        keep the ``str`` items and a caller that wants the price watches for the
        ``Usage``. SSE comment lines — the ``: OPENROUTER PROCESSING`` keep-alive —
        are skipped rather than parsed, which is what crashes a naive reader.
        """
        payload = self._payload(prompt, model=model, system=system, tools=tools,
                                stream=True, params=params)
        with self._request("POST", "/chat/completions", payload,
                           stream=True, timeout=timeout) as response:
            for line in _sse_lines(response):
                if not line.startswith("data:"):
                    continue                     # a comment, or an SSE field we ignore
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                _raise_for_body(chunk)           # mid-stream provider failure
                for choice in chunk.get("choices") or []:
                    piece = ((choice.get("delta") or {}).get("content")) or ""
                    if piece:
                        yield piece
                if chunk.get("usage"):
                    yield Usage.from_payload(chunk["usage"])

    # -- payload -------------------------------------------------------------------

    @staticmethod
    def _payload(prompt: str | Sequence[dict], *, model: str, system: str | None,
                 tools: Sequence[dict] | None, stream: bool, params: dict) -> dict:
        if not model:
            raise BadRequest("no model: pass --model, or set OPENROUTER_MODEL")
        if isinstance(prompt, str):
            messages: list = [{"role": "user", "content": prompt}]
        else:
            messages = [dict(m) for m in prompt]
        if system:
            messages.insert(0, {"role": "system", "content": system})
        if not messages:
            raise BadRequest("no messages: nothing to ask")
        payload: dict = {"model": model, "messages": messages}
        if stream:
            payload["stream"] = True
        if tools:
            payload["tools"] = list(tools)
        payload.update({k: v for k, v in params.items() if v is not None})
        return payload


# ------------------------------------------------------------------------- decoding

def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _read_json(response: Any) -> dict:
    raw = response.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise OpenRouterError(f"OpenRouter sent something that is not JSON: {raw[:200]!r}") from None
    return body if isinstance(body, dict) else {"data": body}


def _sse_lines(response: Any) -> Iterable[str]:
    """Yield decoded lines of an SSE body, whatever size the chunks arrive in."""
    buffer = ""
    while True:
        chunk = response.read(1024)
        if not chunk:
            break
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8", errors="replace")
        buffer += chunk
        while "\n" in buffer:
            line, _, buffer = buffer.partition("\n")
            yield line.strip()
    if buffer.strip():
        yield buffer.strip()


def _error_bits(body: Any) -> tuple:
    """(message, status, code) out of OpenRouter's ``{"error": {...}}`` envelope."""
    if not isinstance(body, dict):
        return "", None, None
    error = body.get("error")
    if not isinstance(error, dict):
        return "", None, None
    message = str(error.get("message") or "").strip()
    status = error.get("code")
    status = status if isinstance(status, int) else None
    metadata = error.get("metadata")
    code = None
    if isinstance(metadata, dict):
        code = metadata.get("error_type") or metadata.get("provider_code")
    return message, status, (str(code) if code else None)


def _raise(status: int | None, message: str, *, code: str | None = None,
           body: Any = None, retry_after: float | None = None) -> None:
    text = message or f"OpenRouter failed with HTTP {status}"
    kw = {"status": status, "code": code, "body": body}
    if status == 401:
        raise AuthError(f"401 {text} — check {_ENV_KEY}", **kw)
    if status == 402:
        raise OutOfCredit(f"402 {text} — the account or the key's credit cap is empty", **kw)
    if status == 403:
        raise Forbidden(f"403 {text}", **kw)
    if status == 408:
        raise Timeout(f"408 {text}", **kw)
    if status == 429:
        raise RateLimited(f"429 {text}", retry_after=retry_after, **kw)
    if status is not None and 500 <= status < 600:
        raise ServerError(f"{status} {text} — OpenRouter or the provider behind it", **kw)
    raise BadRequest(f"{status or '?'} {text}", **kw)


def _from_http_error(exc: urllib.error.HTTPError) -> OpenRouterError:
    try:
        raw = exc.read()
    except Exception:                                        # noqa: BLE001 — best effort
        raw = b""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        body = {"error": {"message": raw[:200]}}
    message, _, code = _error_bits(body)
    retry_after = None
    header = getattr(exc, "headers", None)
    if header is not None:
        retry_after = _as_float(header.get("Retry-After")) or None
    try:
        _raise(exc.code, message or exc.reason or "", code=code, body=body,
               retry_after=retry_after)
    except OpenRouterError as raised:
        return raised
    return OpenRouterError(str(exc))                          # unreachable in practice


def _raise_for_body(body: Any) -> None:
    """An error carried inside a 200 body (a provider that failed mid-flight)."""
    message, status, code = _error_bits(body)
    if message or status:
        _raise(status, message, code=code, body=body)


def _answer_from_body(body: dict) -> ChatAnswer:
    choices = body.get("choices") or []
    first = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):                 # some providers send content parts
        content = "".join(part.get("text", "") for part in content
                          if isinstance(part, dict))
    return ChatAnswer(
        text=content or "",
        model=str(body.get("model") or ""),
        provider=str(body.get("provider") or ""),
        finish_reason=str(first.get("finish_reason") or ""),
        tool_calls=list(message.get("tool_calls") or []),
        usage=Usage.from_payload(body.get("usage")),
        id=str(body.get("id") or ""),
        raw=body,
    )
