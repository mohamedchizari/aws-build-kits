"""Measuring and parsing logic for streamed chat completions. Pure Python, no AWS, no network.

This file produces the numbers the owner will quote (time to first token, output tokens per
second), so it is unit-tested offline in tests/test_streamstats.py against fake streams.

What the stream looks like, and where that was confirmed (read 2026-10-07):

* boto3 invoke_endpoint_with_response_stream returns an event stream. Each event is
  {"PayloadPart": {"Bytes": b"..."}}. "Occasionally, the streaming response splits the chunks over
  multiple payload parts, or it combines multiple chunks into one payload part."
  https://docs.aws.amazon.com/sagemaker/latest/dg/realtime-endpoints-test-endpoints.html
  https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_runtime_InvokeEndpointWithResponseStream.html
* The AWS vLLM container runs vLLM's OpenAI-compatible server, so the bytes are Server-Sent Events:
  lines "data: {json}" separated by a blank line, ending with "data: [DONE]". Each JSON object is a
  chat.completion.chunk whose choices[0].delta has "content" and, for reasoning models, "reasoning".
  With stream_options {"include_usage": true} a chunk carries "usage" with "completion_tokens".
  vLLM v0.30.0 source: vllm/entrypoints/openai/chat_completion/protocol.py (ChatCompletionStreamResponse,
  stream_options) and vllm/entrypoints/generate/base/protocol.py (StreamOptions, DeltaMessage).

Definitions used everywhere in this kit:

* ttft_s             seconds from just before the request is sent to the arrival of the first payload
                     part that contains generated text (content or reasoning). Measured on the client,
                     so it includes the network path from the client to the Region. It also includes the
                     TCP and TLS handshake when the request has to open its connection; 50_invoke.py and
                     60_loadtest.py send warm-up requests that are not recorded so that recorded requests
                     reuse an open connection.
* reasoning_seen     True when the request carried reasoning text: a "reasoning" delta, or answer text
                     that starts with "<think>". ttft_s is then the time to the first REASONING token.
* total_s            seconds from just before the request is sent to the end of the stream.
* ok                 the stream carried generated text, no error, and a proper end: a finish_reason or
                     the "[DONE]" line. A stream that simply stops is a failed request (truncated).
* output_tokens      usage.completion_tokens from the stream when present (tokens_source = "usage").
                     Otherwise the number of text-bearing chunks (tokens_source = "chunks"), which is
                     an approximation: one chunk is usually, not always, one token.
* request_tokens_per_s   output_tokens / total_s. What one caller experiences end to end.
* decode_tokens_per_s    (text chunks - N) / (time of last text chunk - time of first text chunk), where
                     N is the number of text chunks that arrived together with the first one (N is 1
                     unless SageMaker put several tokens into the first payload part). Chunks are what
                     the timing is measured on, so chunks are what is counted: the server's usage count
                     is NOT used here, because it can be higher than the number of chunks (an end token,
                     a chunk that carries two tokens) and would then overstate the rate. It equals
                     tokens per second when every chunk is one token; when the server's count is higher
                     than the chunk count the true token rate is higher than this number. A secondary
                     number. token_chunk_mismatch_requests says in how many requests the two counts differed.
* aggregate_tokens_per_s (per concurrency level) sum of output_tokens over successful requests divided
                     by the wall-clock time of the level. What the endpoint delivers in total.
* output_tokens_per_request_mean, output_tokens_min, output_tokens_max (per level) output_tokens over the
                     successful requests of the level. Without ignore_eos a request may stop before
                     max_tokens, so requests differ: quote "up to max_tokens, mean ...", not max_tokens.
* ttft_p95_s         the 95th percentile, only when the level has at least MIN_REQUESTS_FOR_P95 (20)
                     successful requests. Below that it is left empty ("-"): with 4 requests it is
                     3.85 of a maximum of 4, which is the maximum under another name. ttft_max_s is
                     always given.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable


class SSEParser:
    """Incremental Server-Sent Events parser. feed() accepts bytes cut at any position."""

    def __init__(self) -> None:
        self._buffer = b""
        self._data_lines: list[str] = []

    def feed(self, data: bytes) -> list[str]:
        """Return the data payload of every event completed by these bytes, in order."""
        self._buffer += data
        events: list[str] = []
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                break
            raw = self._buffer[:newline]
            self._buffer = self._buffer[newline + 1:]
            if raw.endswith(b"\r"):
                raw = raw[:-1]
            line = raw.decode("utf-8", errors="replace")
            if line == "":
                if self._data_lines:
                    events.append("\n".join(self._data_lines))
                    self._data_lines = []
                continue
            if line.startswith(":"):
                continue  # comment or keep-alive
            name, separator, value = line.partition(":")
            if not separator:
                continue
            if value.startswith(" "):
                value = value[1:]
            if name == "data":
                self._data_lines.append(value)
        return events

    def flush(self) -> list[str]:
        """Call at end of stream. Returns a final event if the stream ended without a blank line."""
        events: list[str] = []
        if self._buffer:
            raw = self._buffer[:-1] if self._buffer.endswith(b"\r") else self._buffer
            line = raw.decode("utf-8", errors="replace")
            self._buffer = b""
            if line.startswith("data:"):
                value = line[5:]
                self._data_lines.append(value[1:] if value.startswith(" ") else value)
        if self._data_lines:
            events.append("\n".join(self._data_lines))
            self._data_lines = []
        return events


THINK_TAG = "<think>"  # Qwen3's chat template opens reasoning with this tag when no reasoning parser splits it out
REASONING_KEYS = ("reasoning", "reasoning_content")


def delta_has_reasoning(chunk: dict[str, Any]) -> bool:
    """True when one chat.completion.chunk carries reasoning text in a reasoning field."""
    for choice in chunk.get("choices") or []:
        delta = choice.get("delta") or {}
        if any(isinstance(delta.get(key), str) and delta.get(key) for key in REASONING_KEYS):
            return True
    return False


def delta_text(chunk: dict[str, Any]) -> str:
    """Generated text carried by one chat.completion.chunk, answer text and reasoning text together."""
    pieces: list[str] = []
    for choice in chunk.get("choices") or []:
        delta = choice.get("delta") or {}
        for key in ("content", "reasoning", "reasoning_content"):
            value = delta.get(key)
            if isinstance(value, str) and value:
                pieces.append(value)
    return "".join(pieces)


@dataclass
class RequestResult:
    ok: bool
    error: str
    ttft_s: float | None
    total_s: float
    output_tokens: int
    tokens_source: str
    prompt_tokens: int | None
    request_tokens_per_s: float | None
    decode_tokens_per_s: float | None
    text_chunks: int
    finish_reason: str
    saw_done: bool
    text: str = field(default="", repr=False)
    reasoning_seen: bool = False


class StreamRecorder:
    """Feed it payload bytes with the time each part arrived. Ask for result() at the end."""

    def __init__(self, started_at: float, keep_text: bool = False,
                 on_text: Callable[[str], None] | None = None) -> None:
        self.started_at = started_at
        self.keep_text = keep_text
        self.on_text = on_text
        self._parser = SSEParser()
        self.first_text_at: float | None = None
        self.last_text_at: float | None = None
        self.text_chunks = 0
        self.chunks_at_first = 0  # text chunks that arrived at the same instant as the first one
        self.reasoning_seen = False
        self._head = ""           # the first few characters of text, to recognise a leading <think>
        self.completion_tokens: int | None = None
        self.prompt_tokens: int | None = None
        self.finish_reason = ""
        self.saw_done = False
        self.error = ""
        self._text: list[str] = []

    def on_bytes(self, data: bytes, now: float) -> None:
        for payload in self._parser.feed(data):
            self._on_event(payload, now)

    def on_error(self, message: str) -> None:
        if not self.error:
            self.error = message

    def _on_event(self, payload: str, now: float) -> None:
        payload = payload.strip()
        if not payload:
            return
        if payload == "[DONE]":
            self.saw_done = True
            return
        try:
            chunk = json.loads(payload)
        except ValueError:
            self.on_error(f"unparseable stream event: {payload[:120]}")
            return
        if not isinstance(chunk, dict):
            self.on_error(f"unexpected stream event: {payload[:120]}")
            return
        if "error" in chunk and not chunk.get("choices"):
            detail = chunk["error"]
            if isinstance(detail, dict):
                detail = detail.get("message") or json.dumps(detail)
            self.on_error(f"model error in stream: {str(detail)[:200]}")
            return
        if chunk.get("object") == "error":
            self.on_error(f"model error in stream: {str(chunk.get('message', ''))[:200]}")
            return
        usage = chunk.get("usage")
        if isinstance(usage, dict):
            if isinstance(usage.get("completion_tokens"), int):
                self.completion_tokens = usage["completion_tokens"]
            if isinstance(usage.get("prompt_tokens"), int):
                self.prompt_tokens = usage["prompt_tokens"]
        for choice in chunk.get("choices") or []:
            if choice.get("finish_reason"):
                self.finish_reason = str(choice["finish_reason"])
        text = delta_text(chunk)
        if text:
            if self.first_text_at is None:
                self.first_text_at = now
            if now == self.first_text_at:
                self.chunks_at_first += 1
            self.last_text_at = now
            self.text_chunks += 1
            if delta_has_reasoning(chunk):
                self.reasoning_seen = True
            if len(self._head) < 16:
                self._head += text
                if self._head.lstrip().startswith(THINK_TAG):
                    self.reasoning_seen = True
            if self.keep_text:
                self._text.append(text)
            if self.on_text is not None:
                self.on_text(text)

    def result(self, ended_at: float) -> RequestResult:
        for payload in self._parser.flush():
            self._on_event(payload, ended_at)
        total = max(0.0, ended_at - self.started_at)
        if self.completion_tokens is not None:
            tokens, source = self.completion_tokens, "usage"
        else:
            tokens, source = self.text_chunks, "chunks"
        error = self.error
        if not error and self.first_text_at is None:
            error = "stream ended without any generated text"
        if not error and not (self.saw_done or self.finish_reason):
            error = ("stream stopped without a finish_reason and without [DONE] (truncated after "
                     f"{self.text_chunks} text chunk(s))")
        ok = not error
        ttft = None if self.first_text_at is None else max(0.0, self.first_text_at - self.started_at)
        request_rate = tokens / total if ok and total > 0 and tokens > 0 else None
        decode_rate = None
        # Chunks, not the usage count: the window is measured between chunks, so only chunks may be counted in it.
        after_first = self.text_chunks - self.chunks_at_first
        if ok and after_first > 0 and self.first_text_at is not None and self.last_text_at is not None:
            window = self.last_text_at - self.first_text_at
            if window > 0:
                decode_rate = after_first / window
        return RequestResult(
            ok=ok, error=error, ttft_s=ttft, total_s=total, output_tokens=tokens if ok else 0,
            tokens_source=source, prompt_tokens=self.prompt_tokens, request_tokens_per_s=request_rate,
            decode_tokens_per_s=decode_rate, text_chunks=self.text_chunks, finish_reason=self.finish_reason,
            saw_done=self.saw_done, text="".join(self._text), reasoning_seen=self.reasoning_seen,
        )


def consume_event_stream(events: Iterable[dict[str, Any]], clock: Callable[[], float], started_at: float,
                         keep_text: bool = False, on_text: Callable[[str], None] | None = None) -> RequestResult:
    """Read a boto3 response stream (or a fake one) to the end and measure it.

    events yields dicts shaped like the InvokeEndpointWithResponseStream output:
    {"PayloadPart": {"Bytes": b"..."}}, {"ModelStreamError": {...}} or {"InternalStreamFailure": {...}}.
    botocore raises the two error events as exceptions while iterating; those are caught here too.
    """
    recorder = StreamRecorder(started_at, keep_text=keep_text, on_text=on_text)
    try:
        for event in events:
            now = clock()
            if "PayloadPart" in event:
                recorder.on_bytes(event["PayloadPart"].get("Bytes", b""), now)
            elif "ModelStreamError" in event:
                # ErrorCode is listed for ModelStreamError on the API reference page (read 2026-10-07).
                # UNVERIFIED: the "Message" member of ModelStreamError and of InternalStreamFailure. Both are in
                # the botocore 1.43.108 model; the API reference page does not list them. Used for error text only.
                detail = event["ModelStreamError"] or {}
                recorder.on_error(f"ModelStreamError {detail.get('ErrorCode', '')}: {detail.get('Message', '')}".strip())
            elif "InternalStreamFailure" in event:
                detail = event["InternalStreamFailure"] or {}
                recorder.on_error(f"InternalStreamFailure: {detail.get('Message', '')}".strip())
    except Exception as exc:  # noqa: BLE001 - any failure while reading is a failed request, recorded as such
        recorder.on_error(f"{type(exc).__name__}: {exc}"[:300])
    return recorder.result(clock())


def percentile(values: list[float], fraction: float) -> float | None:
    """Linear interpolation between closest ranks (the method numpy calls 'linear'). None for no data."""
    if not values:
        return None
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be between 0 and 1")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


MIN_REQUESTS_FOR_P95 = 20  # below this a p95 is the maximum under another name, so none is given


@dataclass
class LevelSummary:
    label: str
    concurrency: int
    requests: int
    ok: int
    errors: int
    wall_s: float
    ttft_p50_s: float | None
    ttft_p95_s: float | None
    ttft_max_s: float | None
    total_p50_s: float | None
    request_tokens_per_s_p50: float | None
    decode_tokens_per_s_p50: float | None
    output_tokens_total: int
    aggregate_tokens_per_s: float | None
    tokens_source: str
    warmup_requests: int = 0      # requests sent just before this level and NOT recorded (they open the connections)
    reasoning_requests: int = 0   # successful requests that carried reasoning text (ttft_s is then time to first reasoning token)
    output_tokens_per_request_mean: float | None = None  # output_tokens_total / ok
    output_tokens_min: int | None = None
    output_tokens_max: int | None = None
    token_chunk_mismatch_requests: int = 0  # successful requests whose usage token count differs from their chunk count


def summarise_level(label: str, concurrency: int, results: list[RequestResult], wall_s: float,
                    warmup_requests: int = 0) -> LevelSummary:
    good = [r for r in results if r.ok]
    ttfts = [r.ttft_s for r in good if r.ttft_s is not None]
    totals = [r.total_s for r in good]
    request_rates = [r.request_tokens_per_s for r in good if r.request_tokens_per_s is not None]
    decode_rates = [r.decode_tokens_per_s for r in good if r.decode_tokens_per_s is not None]
    tokens = sum(r.output_tokens for r in good)
    sources = sorted({r.tokens_source for r in good})
    per_request = [r.output_tokens for r in good]
    return LevelSummary(
        label=label, concurrency=concurrency, requests=len(results), ok=len(good), errors=len(results) - len(good),
        wall_s=wall_s,
        ttft_p50_s=percentile(ttfts, 0.50),
        ttft_p95_s=percentile(ttfts, 0.95) if len(ttfts) >= MIN_REQUESTS_FOR_P95 else None,
        ttft_max_s=max(ttfts) if ttfts else None,
        total_p50_s=percentile(totals, 0.50),
        request_tokens_per_s_p50=percentile(request_rates, 0.50),
        decode_tokens_per_s_p50=percentile(decode_rates, 0.50),
        output_tokens_total=tokens,
        aggregate_tokens_per_s=(tokens / wall_s) if good and wall_s > 0 else None,
        tokens_source="+".join(sources) if sources else "none",
        warmup_requests=warmup_requests,
        reasoning_requests=sum(1 for r in good if r.reasoning_seen),
        output_tokens_per_request_mean=(tokens / len(good)) if good else None,
        output_tokens_min=min(per_request) if per_request else None,
        output_tokens_max=max(per_request) if per_request else None,
        token_chunk_mismatch_requests=sum(1 for r in good if r.tokens_source == "usage" and r.output_tokens != r.text_chunks),
    )


REQUEST_COLUMNS = [
    "label", "concurrency", "request_index", "ok", "error", "ttft_s", "total_s", "output_tokens", "tokens_source",
    "prompt_tokens", "request_tokens_per_s", "decode_tokens_per_s", "text_chunks", "finish_reason", "saw_done",
    "reasoning_seen",
]
SUMMARY_COLUMNS = list(LevelSummary.__dataclass_fields__.keys())


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4f}"
    return value


def request_row(label: str, concurrency: int, index: int, result: RequestResult) -> dict[str, Any]:
    data = asdict(result)
    data.pop("text", None)
    data.update({"label": label, "concurrency": concurrency, "request_index": index})
    return {column: _cell(data.get(column)) for column in REQUEST_COLUMNS}


def summary_row(summary: LevelSummary) -> dict[str, Any]:
    data = asdict(summary)
    return {column: _cell(data.get(column)) for column in SUMMARY_COLUMNS}


def format_summary_table(summaries: list[LevelSummary]) -> str:
    def show(value: float | None, digits: int = 2) -> str:
        return "-" if value is None else f"{value:.{digits}f}"

    header = (f"{'conc':>4} {'ok/req':>7} {'TTFT p50 s':>10} {'TTFT p95 s':>10} {'req tok/s p50':>13} "
              f"{'decode tok/s p50':>16} {'aggregate tok/s':>15} {'out tok/req':>11} {'tokens from':>11}")
    lines = [header, "-" * len(header)]
    for s in summaries:
        lines.append(
            f"{s.concurrency:>4} {str(s.ok) + '/' + str(s.requests):>7} {show(s.ttft_p50_s, 3):>10} "
            f"{show(s.ttft_p95_s, 3):>10} {show(s.request_tokens_per_s_p50):>13} "
            f"{show(s.decode_tokens_per_s_p50):>16} {show(s.aggregate_tokens_per_s):>15} "
            f"{show(s.output_tokens_per_request_mean, 1):>11} {s.tokens_source:>11}"
        )
    return "\n".join(lines)
