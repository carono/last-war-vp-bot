# OpenRouter's HTTP API, as read from its own documentation

What is written here was read out of OpenRouter's published documentation
(`https://openrouter.ai/docs/llms-full.txt`, and the live `GET /api/v1/models`) on
**2026-09-02**, and nothing here is a guess. It is the reference behind
`tools/lib/openrouter.py` and `tools/openrouter.py`; when the two disagree, one of them
is out of date and this file says which day it was true.

There is **no OpenAPI document** at `https://openrouter.ai/docs/openapi.json` — that URL
answers 404. The machine-readable source the vendor offers is `llms-full.txt` (~3.7 MB of
the whole documentation site), so that is what was read.

## The base URL and the key

    https://openrouter.ai/api/v1

Authentication is a bearer token:

    Authorization: Bearer <key>
    Content-Type: application/json

Two optional attribution headers are accepted and used for OpenRouter's own public
rankings — `HTTP-Referer` (a site URL) and `X-OpenRouter-Title` (a site name). Neither is
required, and nothing breaks when they are absent.

The dialect is OpenAI's Chat Completions, which is why any OpenAI SDK works against it by
pointing `base_url` here. This repository does not take that dependency: the client is
`urllib` and `json`.

**The key belongs in `.env` (`OPENROUTER_API_KEY`) and nowhere else.** This repository is
public; see the rule in `CLAUDE.md`. The address itself is `OPENROUTER_BASE_URL` in front
of the default above, so a machine behind a proxy is a variable and not a code change.

## `GET /models`

Returns `{"data": [...]}` — 421 entries on the day this was read. The fields that matter
to a caller choosing one:

| field | meaning |
| --- | --- |
| `id` | what you send as `model`, e.g. `vendor/model-name`, optionally with a `:free` variant suffix |
| `canonical_slug` | the dated build the id currently points at |
| `name` | the human name |
| `context_length` | tokens the model will take |
| `pricing.prompt` / `pricing.completion` | **USD per token, as decimal STRINGS** — multiply by 1e6 to compare per-million prices |
| `pricing.input_cache_read` / `input_cache_write` | per-token prices for prompt caching, when the model has it |
| `architecture.input_modalities` / `output_modalities` | `text`, `image`, `file`, … |
| `top_provider.max_completion_tokens` | the output ceiling of the provider serving it |
| `supported_parameters` | which sampling/feature keys this model actually honours (`tools`, `reasoning`, `response_format`, …) |

Prices arriving as strings rather than numbers is the trap worth naming: `"0.00001"` and
`0` both occur, and a free model is one whose prompt **and** completion prices are zero.

## `POST /chat/completions`

The request is the OpenAI shape:

```json
{
  "model": "vendor/model-name",
  "messages": [{"role": "system", "content": "..."},
               {"role": "user", "content": "..."}],
  "stream": false,
  "tools": [{"type": "function",
             "function": {"name": "get_weather", "description": "...",
                          "parameters": {"type": "object", "properties": {}}}}],
  "tool_choice": "auto"
}
```

Sampling parameters are optional and documented individually: `temperature` (0–2),
`top_p` (0–1), `top_k` (≥0), `frequency_penalty` / `presence_penalty` (−2–2),
`repetition_penalty` (0–2), `min_p`, `top_a`, plus `max_tokens`, `stop`,
`response_format`, `seed`, `reasoning`. **A parameter you omit is omitted upstream** —
OpenRouter does not substitute a default of its own, so the provider's default applies.
The "default" values in the documentation are conventional, not injected. Sending a value
explicitly is forwarded and can differ from omitting it (it can change a provider's cache
key).

The response is a chat completion: `id`, `model`, `provider`, `choices[0].message`
(`content`, and `tool_calls` when the model asked for one), `choices[0].finish_reason`,
and a `usage` object.

Tool calls come back in the standard shape — `message.tool_calls[]` with
`{id, type: "function", function: {name, arguments}}`, `arguments` being a JSON **string**
— and `finish_reason` is then `tool_calls`. Replying to one means appending the assistant
message and a `{"role": "tool", "tool_call_id": ..., "content": ...}` message.

### `usage` — the part that says what it cost

Included **always**, on every response, without asking. (`usage: {include: true}` and
`stream_options: {include_usage: true}` are documented as deprecated and now have no
effect.) On a stream it rides on the final SSE message.

```json
{
  "usage": {
    "prompt_tokens": 194,
    "completion_tokens": 2,
    "total_tokens": 196,
    "cost": 0.95,
    "cost_details": {"upstream_inference_cost": 19},
    "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 100, "audio_tokens": 0},
    "completion_tokens_details": {"reasoning_tokens": 0}
  }
}
```

* `cost` — what was charged to the account, in credits (the account's own currency unit).
* `cost_details.upstream_inference_cost` — what the upstream provider charged; only
  meaningful for BYOK requests, 0/null otherwise.
* `cached_tokens` are tokens **read** from the prompt cache, `cache_write_tokens` those
  **written** to it.
* Token counts use the model's native tokenizer.

The same figures can be fetched afterwards by the completion's `id` through the
generation endpoint, but there is no reason to: they are already in the answer.

## Streaming

`"stream": true` turns the response into Server-Sent Events. Each event is a
`data: {...}` line carrying a `chat.completion.chunk`; text arrives as
`choices[0].delta.content`; the stream ends with `data: [DONE]`.

**Two things that break a hand-written reader**, both documented and both pinned by our
tests:

1. OpenRouter sends SSE **comments** to keep the connection alive:

       : OPENROUTER PROCESSING

   A line starting with `:` is not JSON. Feeding it to a parser throws, and unhandled it
   kills the loop. Skip every line that starts with `:`.
2. A `data:` line can be split across reads, so the reader must buffer and cut on `\n`
   rather than assume one read is one line.

## Errors

The envelope is the same everywhere:

```json
{"error": {"code": 429, "message": "Rate limit exceeded",
           "metadata": {"error_type": "rate_limit_exceeded", "provider_code": "rate_limited"}}}
```

`error.code` mirrors the HTTP status when the failure happened **before** generation
started. The documented codes:

| status | meaning | what to do |
| --- | --- | --- |
| 400 | bad request — invalid or missing parameters, CORS | fix the request |
| 401 | invalid credentials — expired OAuth session, disabled or wrong key | check `OPENROUTER_API_KEY` |
| 402 | out of credit — negative account balance, or the key's own credit cap is spent | add credits, or raise/await the key's cap |
| 403 | forbidden — permissions, a guardrail block, or a moderation flag (`metadata.reasons`, `flagged_input`) | do not retry blindly |
| 408 | the request timed out | retry |
| 429 | rate limited — platform limit or the upstream provider's | back off; honour `Retry-After` |
| 502 | the chosen model is down, or returned an invalid response | retry, or fall back to another model |
| 503 | no provider meets the routing requirements | relax routing, or pick another model |

`error.metadata.error_type` is the stable, normalised vocabulary across skins;
`provider_code` is the upstream's own code where available. On a 500 the message is
replaced with a generic string and `provider_code` is dropped, but `error_type` (`server`)
remains.

`Retry-After` (seconds) may be present on **429 and 503**. On a platform 429 the error
response also carries `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset`;
successful responses carry no rate-limit headers at all.

### The status is committed before the answer exists

OpenRouter sends `200 OK` as soon as a provider accepts the request — before a single
token is produced. Everything that fails after that is reported **in the body**, not in the
status: a streaming request gets an SSE event with `finish_reason: "error"` and an `error`
object; a non-streaming request gets an error body under a 200. So a client must check for
`error` in a 200 body as well as in a 4xx/5xx, which is the one non-obvious thing here.

Failover also stops once any output has reached the caller — the first provider's partial
answer is already in hand.

## Limits

Two different things, with two different errors:

* **Credit limits** — how much may be spent: the account balance, plus an optional
  per-key cap. Exceeded → **402**. Read them with `GET /key`.
* **Rate limits** — how many requests: free-variant request caps (per minute and per day,
  scaled by how many credits the account has ever bought) and Cloudflare DDoS protection.
  Exceeded → **429**.

Extra accounts or keys do not raise capacity: it is governed globally, though different
models have different limits.

## `GET /key`

Returns `{"data": {...}}` describing the key in use:

| field | meaning |
| --- | --- |
| `label` | the key's name |
| `limit` / `limit_remaining` | the per-key credit cap and what is left (`null` = unlimited) |
| `limit_reset` | how the cap resets, `null` if never |
| `usage`, `usage_daily`, `usage_weekly`, `usage_monthly` | credits spent (all time / UTC day / UTC week from Monday / UTC month) |
| `byok_usage*` | the same for external BYOK usage |
| `is_free_tier` | whether the account has ever bought credits |
| `rate_limit` | deprecated, safe to ignore |

Calling this before requests start failing is the documented way to watch a budget.

## What this repository implements

`tools/lib/openrouter.py` — `Client.models()`, `Client.key_info()`, `Client.chat()`,
`Client.chat_stream()`, a `Usage` that carries tokens **and** cost, and one exception class
per reaction (`NotConfigured`, `AuthError`, `OutOfCredit`, `Forbidden`, `BadRequest`,
`RateLimited` with `retry_after`, `ServerError`, `Timeout`).

`tools/openrouter.py` — the terminal wrapper: `--models` (with `--search`, `--free`,
`--limit`), `--model` + `--prompt` (`-` reads stdin), `--stream`, `--key`, `--json`, and
the sampling flags. Offline tests: `tests/test_openrouter.py`.
