r"""The OpenRouter client, offline — no socket is opened by this file.

    python3 tests/test_openrouter.py
    C:\Python312\python.exe tests\test_openrouter.py

Every case drives `tools/lib/openrouter.py` through a stand-in opener, so what is
pinned is the code's own reading of the protocol described in
`docs/research/openrouter-api.md`:

  * the KEY is never invented — no key at all raises `NotConfigured` and no request is
    built, which is what keeps an empty `Authorization` header off the wire;
  * environment first, then `.env`, then the published default — the same
    environment-in-front-of-a-default shape the rest of `tools/lib` uses;
  * the four statuses that want four different reactions are four different classes —
    401 / 402 / 429 (with `Retry-After`) / 5xx;
  * an error carried inside a 200 body raises too: once streaming has started the
    status is committed, so a provider failure arrives in the body;
  * SSE parsing skips the `: OPENROUTER PROCESSING` comment (feeding it to a JSON
    parser is what crashes a naive reader), survives a `data:` line split across two
    reads, and ends at `[DONE]`;
  * `usage` is decoded whole — tokens, reasoning, cached, and the credits the call
    cost — because a call whose price is invisible is a call nobody can budget.
"""
from __future__ import annotations

TIER = "offline"   # no Tk, no display, no game, no network — see tools/run_tests.py

import io
import json
import sys
import urllib.error
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (str(_REPO), str(_REPO / "tools" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import openrouter as api                                     # noqa: E402


# --------------------------------------------------------------------- the stand-ins

class FakeResponse(io.BytesIO):
    """A urlopen result: a byte stream that is also a context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FakeOpener:
    """Records the requests it was given and replays canned answers."""

    def __init__(self, *bodies):
        self.bodies = list(bodies)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        body = self.bodies.pop(0) if self.bodies else b""
        if isinstance(body, Exception):
            raise body
        if isinstance(body, str):
            body = body.encode("utf-8")
        return FakeResponse(body)


def _http_error(status, payload, headers=None):
    return urllib.error.HTTPError(
        "https://example.invalid/api/v1/chat/completions", status, "err",
        headers or {}, io.BytesIO(json.dumps(payload).encode("utf-8")))


def _client(*bodies, key="test-key"):
    opener = FakeOpener(*bodies)
    return api.Client(api_key=key, base_url="https://example.invalid/api/v1",
                      opener=opener), opener


CHAT_BODY = {
    "id": "gen-0000",
    "model": "vendor/model-name",
    "provider": "SomeProvider",
    "choices": [{
        "index": 0,
        "finish_reason": "stop",
        "message": {"role": "assistant", "content": "four words right here"},
    }],
    "usage": {
        "prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15,
        "cost": 0.000012,
        "completion_tokens_details": {"reasoning_tokens": 2},
        "prompt_tokens_details": {"cached_tokens": 8},
        "cost_details": {"upstream_inference_cost": 0.00001},
    },
}


# -------------------------------------------------------------------- configuration

def test_no_key_raises_before_any_request():
    client = api.Client(api_key="", base_url="https://example.invalid/api/v1",
                        opener=FakeOpener())
    assert not client.configured
    try:
        client.models()
    except api.NotConfigured as exc:
        assert "OPENROUTER_API_KEY" in str(exc)
    else:
        raise AssertionError("a missing key must stop the call, not send an empty header")


def test_environment_beats_dotenv_and_default():
    import os
    before = os.environ.get("OPENROUTER_BASE_URL")
    try:
        os.environ["OPENROUTER_BASE_URL"] = "https://example.invalid/other/v1"
        assert api.base_url() == "https://example.invalid/other/v1"
        del os.environ["OPENROUTER_BASE_URL"]
        # …and with nothing set anywhere, the published address, never a machine's own.
        assert api.base_url().startswith("https://openrouter.ai/")
    finally:
        if before is None:
            os.environ.pop("OPENROUTER_BASE_URL", None)
        else:
            os.environ["OPENROUTER_BASE_URL"] = before


def test_the_key_travels_as_a_bearer_header():
    client, opener = _client(json.dumps(CHAT_BODY))
    client.chat("hello", model="vendor/model-name")
    request = opener.requests[0]
    assert request.get_header("Authorization") == "Bearer test-key"
    assert request.full_url == "https://example.invalid/api/v1/chat/completions"


# ---------------------------------------------------------------------------- models

def test_models_returns_the_data_array():
    body = {"data": [{"id": "vendor/a", "pricing": {"prompt": "0.000001"}},
                     {"id": "vendor/b", "pricing": {"prompt": "0"}}]}
    client, opener = _client(json.dumps(body))
    models = client.models()
    assert [m["id"] for m in models] == ["vendor/a", "vendor/b"]
    assert opener.requests[0].get_method() == "GET"
    assert opener.requests[0].full_url.endswith("/models")


def test_key_info_returns_the_limits():
    body = {"data": {"label": "k", "limit": 5.0, "limit_remaining": 4.5, "usage": 0.5}}
    client, _ = _client(json.dumps(body))
    assert client.key_info()["limit_remaining"] == 4.5


# ------------------------------------------------------------------------------ chat

def test_chat_builds_the_payload_and_decodes_the_answer():
    client, opener = _client(json.dumps(CHAT_BODY))
    answer = client.chat("hello", model="vendor/model-name", system="be brief",
                         temperature=0.2, max_tokens=None)
    payload = json.loads(opener.requests[0].data.decode("utf-8"))
    assert payload["model"] == "vendor/model-name"
    assert payload["messages"] == [{"role": "system", "content": "be brief"},
                                   {"role": "user", "content": "hello"}]
    assert payload["temperature"] == 0.2
    assert "max_tokens" not in payload, "a parameter nobody set must not be invented"
    assert "stream" not in payload
    assert answer.text == "four words right here"
    assert answer.finish_reason == "stop"
    assert answer.provider == "SomeProvider"


def test_usage_carries_the_tokens_and_the_price():
    client, _ = _client(json.dumps(CHAT_BODY))
    usage = client.chat("hello", model="vendor/model-name").usage
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (11, 4, 15)
    assert usage.cost == 0.000012
    assert usage.reasoning_tokens == 2
    assert usage.cached_tokens == 8
    assert usage.upstream_cost == 0.00001
    assert usage.as_dict()["cost"] == 0.000012


def test_a_message_list_and_tools_travel_as_given():
    client, opener = _client(json.dumps({
        "choices": [{"message": {"content": None, "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "get_weather", "arguments": "{}"}}]},
            "finish_reason": "tool_calls"}]}))
    tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}]
    answer = client.chat([{"role": "user", "content": "weather?"}],
                         model="vendor/model-name", tools=tools)
    payload = json.loads(opener.requests[0].data.decode("utf-8"))
    assert payload["tools"] == tools
    assert answer.text == ""
    assert answer.tool_calls[0]["function"]["name"] == "get_weather"
    assert answer.finish_reason == "tool_calls"


def test_content_parts_are_joined():
    client, _ = _client(json.dumps({"choices": [{"message": {
        "content": [{"type": "text", "text": "a "}, {"type": "text", "text": "b"}]}}]}))
    assert client.chat("x", model="vendor/model-name").text == "a b"


def test_a_model_is_required():
    client, _ = _client()
    try:
        client.chat("hello", model="")
    except api.BadRequest as exc:
        assert "no model" in str(exc)
    else:
        raise AssertionError("a chat with no model must not be sent")


# ---------------------------------------------------------------------------- errors

def test_401_is_an_auth_error():
    client, _ = _client(_http_error(401, {"error": {"code": 401, "message": "No auth"}}))
    try:
        client.chat("x", model="vendor/model-name")
    except api.AuthError as exc:
        assert exc.status == 401
    else:
        raise AssertionError("401 must be told apart from every other failure")


def test_402_is_out_of_credit():
    client, _ = _client(_http_error(402, {"error": {"code": 402, "message": "no credits"}}))
    try:
        client.chat("x", model="vendor/model-name")
    except api.OutOfCredit as exc:
        assert exc.status == 402
    else:
        raise AssertionError("402 means top up, not retry")


def test_429_carries_retry_after_and_the_typed_code():
    error = _http_error(429, {"error": {"code": 429, "message": "Rate limit exceeded",
                                        "metadata": {"error_type": "rate_limit_exceeded"}}},
                        headers={"Retry-After": "60"})
    client, _ = _client(error)
    try:
        client.chat("x", model="vendor/model-name")
    except api.RateLimited as exc:
        assert exc.retry_after == 60.0
        assert exc.code == "rate_limit_exceeded"
    else:
        raise AssertionError("429 must arrive with how long to wait")


def test_5xx_is_a_server_error():
    client, _ = _client(_http_error(503, {"error": {"code": 503, "message": "down"}}))
    try:
        client.chat("x", model="vendor/model-name")
    except api.ServerError as exc:
        assert exc.status == 503
    else:
        raise AssertionError("503 is worth retrying and must say so by its class")


def test_an_error_inside_a_200_body_still_raises():
    body = {"error": {"code": 429, "message": "Rate limit exceeded",
                      "metadata": {"error_type": "rate_limit_exceeded"}},
            "choices": [{"delta": {"content": ""}, "finish_reason": "error"}]}
    client, _ = _client(json.dumps(body))
    try:
        client.chat("x", model="vendor/model-name")
    except api.RateLimited:
        pass
    else:
        raise AssertionError("a provider failure after the status was sent must not "
                             "be read as an empty answer")


def test_a_body_that_is_not_json_says_so():
    client, _ = _client(b"<html>gateway</html>")
    try:
        client.chat("x", model="vendor/model-name")
    except api.OpenRouterError as exc:
        assert "not JSON" in str(exc)
    else:
        raise AssertionError("an HTML error page must not be swallowed")


def test_an_unreachable_host_is_not_a_traceback():
    client, _ = _client(urllib.error.URLError("Name or service not known"))
    try:
        client.chat("x", model="vendor/model-name")
    except api.OpenRouterError as exc:
        assert "cannot reach OpenRouter" in str(exc)
    else:
        raise AssertionError("a dead network must arrive as our own error")


def test_a_timeout_is_its_own_class():
    client, _ = _client(urllib.error.URLError(TimeoutError("timed out")))
    try:
        client.chat("x", model="vendor/model-name")
    except api.Timeout:
        pass
    else:
        raise AssertionError("a timeout must be distinguishable from a refusal")


# ------------------------------------------------------------------------- streaming

STREAM = (
    ": OPENROUTER PROCESSING\n"
    'data: {"choices":[{"delta":{"content":"one "}}]}\n'
    "\n"
    ": OPENROUTER PROCESSING\n"
    'data: {"choices":[{"delta":{"content":"two"}}]}\n'
    'data: {"choices":[{"delta":{"content":""}}],'
    '"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5,"cost":0.0000004}}\n'
    "data: [DONE]\n"
)


def test_stream_yields_deltas_then_usage_and_skips_comments():
    client, opener = _client(STREAM)
    items = list(client.chat_stream("count", model="vendor/model-name"))
    text = "".join(i for i in items if isinstance(i, str))
    usages = [i for i in items if isinstance(i, api.Usage)]
    assert text == "one two"
    assert len(usages) == 1 and usages[0].total_tokens == 5 and usages[0].cost == 0.0000004
    payload = json.loads(opener.requests[0].data.decode("utf-8"))
    assert payload["stream"] is True
    assert opener.requests[0].get_header("Accept") == "text/event-stream"


def test_stream_survives_a_line_split_across_reads():
    class Chopped(FakeResponse):
        def read(self, size=-1):          # one byte at a time — the worst chunking
            return super().read(1)

    class Opener:
        def __call__(self, request, timeout=None):
            return Chopped(STREAM.encode("utf-8"))

    client = api.Client(api_key="k", base_url="https://example.invalid/api/v1",
                        opener=Opener())
    items = list(client.chat_stream("count", model="vendor/model-name"))
    assert "".join(i for i in items if isinstance(i, str)) == "one two"


def test_stream_stops_at_done_and_ignores_what_follows():
    client, _ = _client(STREAM + 'data: {"choices":[{"delta":{"content":"late"}}]}\n')
    text = "".join(i for i in client.chat_stream("count", model="vendor/model-name")
                   if isinstance(i, str))
    assert "late" not in text


def test_a_mid_stream_error_event_raises():
    body = ('data: {"choices":[{"delta":{"content":"partial"}}]}\n'
            'data: {"error":{"code":502,"message":"provider disconnected",'
            '"metadata":{"error_type":"server"}},'
            '"choices":[{"delta":{"content":""},"finish_reason":"error"}]}\n')
    client, _ = _client(body)
    stream = client.chat_stream("x", model="vendor/model-name")
    assert next(stream) == "partial"
    try:
        next(stream)
    except api.ServerError as exc:
        assert exc.status == 502
    else:
        raise AssertionError("a stream that died mid-answer must not end quietly")


# ----------------------------------------------------------------------------- CLI

def test_cli_without_a_key_exits_three_and_says_not_configured():
    """The CLI's own refusal path: exit 3, no request, whatever this machine has.

    The key lookup is pointed at an empty directory for the duration, so a real
    `.env` on the machine running the tests neither passes the test nor is touched.
    """
    import importlib.util
    import os
    import tempfile

    spec = importlib.util.spec_from_file_location(
        "tools_openrouter_cli", _REPO / "tools" / "openrouter.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    before = os.environ.get("OPENROUTER_API_KEY")
    saved_root = api._repo_root
    try:
        with tempfile.TemporaryDirectory() as empty:
            os.environ["OPENROUTER_API_KEY"] = ""
            api._repo_root = lambda _p=Path(empty): _p       # no .env to be found
            code = module.main(["--models"])
            assert code == 3, f"an unconfigured CLI must exit 3, not {code}"
    finally:
        api._repo_root = saved_root
        if before is None:
            os.environ.pop("OPENROUTER_API_KEY", None)
        else:
            os.environ["OPENROUTER_API_KEY"] = before


def test_a_dotenv_key_is_found_when_the_environment_is_empty():
    """The other half: with nothing exported, the git-ignored `.env` answers."""
    import os
    import tempfile

    before = os.environ.get("OPENROUTER_API_KEY")
    saved_root = api._repo_root
    try:
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / ".env").write_text(
                "# a comment\nOTHER=1\nOPENROUTER_API_KEY=\"from-dotenv\"\n",
                encoding="utf-8")
            os.environ.pop("OPENROUTER_API_KEY", None)
            api._repo_root = lambda _p=Path(home): _p
            assert api.api_key() == "from-dotenv"
    finally:
        api._repo_root = saved_root
        if before is not None:
            os.environ["OPENROUTER_API_KEY"] = before


def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
