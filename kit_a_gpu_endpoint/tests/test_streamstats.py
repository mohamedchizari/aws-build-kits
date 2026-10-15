"""Offline tests for the measuring and parsing logic, against fake streaming responses.

These are the tests that stand behind the numbers the owner will quote.
"""

from __future__ import annotations

import json

import pytest

import streamstats
from streamstats import SSEParser, StreamRecorder, consume_event_stream, percentile, summarise_level


def chunk(content=None, reasoning=None, role=None, finish=None, usage=None, choices=True) -> bytes:
    delta = {}
    if role is not None:
        delta["role"] = role
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning"] = reasoning
    payload = {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1, "model": "m",
               "choices": [{"index": 0, "delta": delta, "finish_reason": finish}] if choices else []}
    if usage is not None:
        payload["usage"] = usage
    return b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n"


DONE = b"data: [DONE]\n\n"


def part(data: bytes) -> dict:
    return {"PayloadPart": {"Bytes": data}}


class TimedStream:
    """A fake event stream. Each item is (arrival time, event); iterating sets the fake clock."""

    def __init__(self, items, end_time):
        self.items = items
        self.end_time = end_time
        self.now = None

    def clock(self):
        return self.now

    def __iter__(self):
        for arrival, event in self.items:
            self.now = arrival
            if isinstance(event, Exception):
                raise event
            yield event
        self.now = self.end_time


def measure(items, end_time, started_at=100.0, **kwargs):
    stream = TimedStream(items, end_time)
    stream.now = started_at
    return consume_event_stream(stream, stream.clock, started_at, **kwargs)


# ---------------------------------------------------------------- SSE parsing

def test_sse_single_event():
    assert SSEParser().feed(b"data: hello\n\n") == ["hello"]


def test_sse_two_events_in_one_feed():
    assert SSEParser().feed(b"data: a\n\ndata: b\n\n") == ["a", "b"]


def test_sse_split_at_every_byte_position_gives_the_same_events():
    stream = chunk(role="assistant") + chunk(content="Hel") + chunk(content="lo é世") + chunk(
        usage={"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11}, choices=False) + DONE
    whole = SSEParser().feed(stream)
    assert len(whole) == 5
    for cut in range(1, len(stream)):
        parser = SSEParser()
        events = parser.feed(stream[:cut]) + parser.feed(stream[cut:]) + parser.flush()
        assert events == whole, f"different events when the stream is cut at byte {cut}"


def test_sse_one_byte_at_a_time():
    stream = chunk(content="a") + chunk(content="b") + DONE
    parser = SSEParser()
    events = []
    for index in range(len(stream)):
        events += parser.feed(stream[index:index + 1])
    assert len(events) == 3 and events[-1] == "[DONE]"


def test_sse_crlf_line_endings():
    assert SSEParser().feed(b"data: a\r\n\r\ndata: b\r\n\r\n") == ["a", "b"]


def test_sse_comments_and_unknown_fields_are_ignored():
    assert SSEParser().feed(b": keep-alive\n\nevent: message\nid: 7\ndata: x\n\n") == ["x"]


def test_sse_multi_line_data_is_joined():
    assert SSEParser().feed(b"data: one\ndata: two\n\n") == ["one\ntwo"]


def test_sse_data_without_space_after_colon():
    assert SSEParser().feed(b"data:x\n\n") == ["x"]


def test_sse_flush_returns_event_missing_final_blank_line():
    parser = SSEParser()
    assert parser.feed(b"data: tail") == []
    assert parser.flush() == ["tail"]
    assert parser.flush() == []


# ---------------------------------------------------------------- delta text

def test_delta_text_reads_content_reasoning_and_legacy_reasoning_content():
    assert streamstats.delta_text({"choices": [{"delta": {"content": "a"}}]}) == "a"
    assert streamstats.delta_text({"choices": [{"delta": {"reasoning": "b"}}]}) == "b"
    assert streamstats.delta_text({"choices": [{"delta": {"reasoning_content": "c"}}]}) == "c"


def test_delta_text_is_empty_for_role_only_null_and_usage_only_chunks():
    assert streamstats.delta_text({"choices": [{"delta": {"role": "assistant", "content": ""}}]}) == ""
    assert streamstats.delta_text({"choices": [{"delta": {"content": None}}]}) == ""
    assert streamstats.delta_text({"choices": [], "usage": {"completion_tokens": 3}}) == ""
    assert streamstats.delta_text({}) == ""


# ---------------------------------------------------------------- one request

def test_exact_numbers_for_a_normal_stream_with_usage():
    items = [(100.5, part(chunk(role="assistant", content="")))]          # role only: not the first token
    items.append((101.0, part(chunk(content="tok0"))))                     # first token at +1.0 s
    for index in range(1, 20):                                             # 19 more, last one at 103.0
        items.append((101.0 + index * (2.0 / 19), part(chunk(content=f"tok{index}"))))
    items.append((103.1, part(chunk(content="", finish="length"))))
    items.append((103.15, part(chunk(usage={"prompt_tokens": 30, "completion_tokens": 21, "total_tokens": 51},
                                     choices=False))))
    items.append((103.15, part(DONE)))
    result = measure(items, end_time=103.2)
    assert result.ok and result.error == ""
    assert result.ttft_s == pytest.approx(1.0)
    assert result.total_s == pytest.approx(3.2)
    assert result.output_tokens == 21 and result.tokens_source == "usage"
    assert result.prompt_tokens == 30
    assert result.text_chunks == 20
    assert result.request_tokens_per_s == pytest.approx(21 / 3.2)
    # Round 2: the rate counts the 20 chunks that were timed, not the 21 tokens the server reports
    # (the reviewed code gave (21 - 1) / 2.0 = 10.0 for 19 gaps in 2.0 s).
    assert result.decode_tokens_per_s == pytest.approx((20 - 1) / 2.0)
    assert result.finish_reason == "length"
    assert result.saw_done is True


def test_without_usage_tokens_are_counted_from_chunks_and_labelled():
    items = [(100.2, part(chunk(content="a"))), (100.4, part(chunk(content="b"))),
             (100.6, part(chunk(content="c"))), (100.6, part(DONE))]
    result = measure(items, end_time=100.7)
    assert result.ok
    assert result.output_tokens == 3 and result.tokens_source == "chunks"
    assert result.decode_tokens_per_s == pytest.approx(2 / 0.4)


def test_time_to_first_token_counts_reasoning_text():
    items = [(100.3, part(chunk(reasoning="thinking"))), (100.9, part(chunk(content="answer"))), (100.9, part(DONE))]
    result = measure(items, end_time=101.0)
    assert result.ttft_s == pytest.approx(0.3)


def test_payload_parts_that_split_one_sse_event_use_the_arrival_time_of_the_completing_part():
    whole = chunk(content="hello")
    items = [(100.4, part(whole[:17])), (100.9, part(whole[17:])), (101.0, part(DONE))]
    result = measure(items, end_time=101.0)
    assert result.ok and result.text_chunks == 1
    assert result.ttft_s == pytest.approx(0.9)


def test_several_sse_events_combined_in_one_payload_part():
    combined = chunk(content="a") + chunk(content="b") + chunk(content="c")
    usage = chunk(usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}, choices=False)
    result = measure([(100.5, part(combined)), (100.8, part(usage + DONE))], end_time=100.8)
    assert result.ok and result.text_chunks == 3 and result.output_tokens == 3
    assert result.ttft_s == pytest.approx(0.5)
    assert result.decode_tokens_per_s is None  # all text arrived at the same instant: no rate can be stated


def test_keep_text_and_on_text_callback():
    seen = []
    items = [(100.1, part(chunk(content="Hel"))), (100.2, part(chunk(content="lo"))), (100.2, part(DONE))]
    result = measure(items, end_time=100.3, keep_text=True, on_text=seen.append)
    assert result.text == "Hello" and seen == ["Hel", "lo"]


def test_stream_with_no_text_is_a_failed_request():
    result = measure([(100.5, part(chunk(role="assistant"))), (100.6, part(DONE))], end_time=100.6)
    assert not result.ok
    assert "without any generated text" in result.error
    assert result.ttft_s is None and result.output_tokens == 0 and result.request_tokens_per_s is None


def test_empty_stream_is_a_failed_request():
    result = measure([], end_time=100.0)
    assert not result.ok


def test_model_stream_error_event_is_recorded():
    items = [(100.2, part(chunk(content="a"))),
             (100.3, {"ModelStreamError": {"ErrorCode": "ModelInvocationTimeExceeded", "Message": "too slow"}})]
    result = measure(items, end_time=100.3)
    assert not result.ok and "ModelStreamError" in result.error and "too slow" in result.error
    assert result.output_tokens == 0


def test_internal_stream_failure_event_is_recorded():
    result = measure([(100.2, {"InternalStreamFailure": {"Message": "boom"}})], end_time=100.2)
    assert not result.ok and "InternalStreamFailure" in result.error


def test_exception_while_iterating_is_recorded_not_raised():
    items = [(100.2, part(chunk(content="a"))), (100.4, RuntimeError("connection reset"))]
    result = measure(items, end_time=100.4)
    assert not result.ok and "connection reset" in result.error
    assert result.total_s == pytest.approx(0.4)


def test_error_object_inside_the_stream_is_a_failed_request():
    body = b'data: {"error": {"message": "maximum context length exceeded", "code": 400}}\n\n'
    result = measure([(100.2, part(body))], end_time=100.2)
    assert not result.ok and "maximum context length" in result.error


def test_vllm_style_error_object_is_a_failed_request():
    body = b'data: {"object": "error", "message": "bad request", "code": 400}\n\n'
    result = measure([(100.2, part(body))], end_time=100.2)
    assert not result.ok and "bad request" in result.error


def test_unparseable_event_is_a_failed_request():
    result = measure([(100.2, part(b"data: {not json}\n\n"))], end_time=100.2)
    assert not result.ok and "unparseable" in result.error


def test_single_token_answer_has_no_decode_rate_but_has_a_request_rate():
    usage = chunk(usage={"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}, choices=False)
    result = measure([(100.5, part(chunk(content="Yes"))), (100.5, part(usage + DONE))], end_time=101.0)
    assert result.ok and result.output_tokens == 1
    assert result.decode_tokens_per_s is None
    assert result.request_tokens_per_s == pytest.approx(1.0)


def test_recorder_can_be_fed_directly():
    recorder = StreamRecorder(started_at=10.0)
    recorder.on_bytes(chunk(content="a"), 10.25)
    recorder.on_bytes(chunk(content="b"), 10.75)
    result = recorder.result(ended_at=11.0)
    assert result.ttft_s == pytest.approx(0.25) and result.total_s == pytest.approx(1.0)


# ---------------------------------------------------------------- percentiles and level summaries

def test_percentile_linear_interpolation():
    values = [1.0, 2.0, 3.0, 4.0]
    assert percentile(values, 0.5) == pytest.approx(2.5)
    assert percentile(values, 0.95) == pytest.approx(3.85)
    assert percentile(values, 0.0) == 1.0 and percentile(values, 1.0) == 4.0
    assert percentile([7.0], 0.95) == 7.0
    assert percentile([], 0.5) is None
    assert percentile([3.0, 1.0, 2.0], 0.5) == 2.0  # input order does not matter
    with pytest.raises(ValueError):
        percentile(values, 1.5)


def good(ttft, total, tokens, decode=None):
    return streamstats.RequestResult(ok=True, error="", ttft_s=ttft, total_s=total, output_tokens=tokens,
                                     tokens_source="usage", prompt_tokens=10, request_tokens_per_s=tokens / total,
                                     decode_tokens_per_s=decode, text_chunks=tokens, finish_reason="length",
                                     saw_done=True)


def bad(total=0.5):
    return streamstats.RequestResult(ok=False, error="ThrottlingException: slow down", ttft_s=None, total_s=total,
                                     output_tokens=0, tokens_source="none", prompt_tokens=None,
                                     request_tokens_per_s=None, decode_tokens_per_s=None, text_chunks=0,
                                     finish_reason="", saw_done=False)


def test_level_summary_numbers():
    results = [good(0.2, 4.0, 200, 50.0), good(0.4, 5.0, 200, 45.0), good(0.6, 8.0, 200, 30.0), bad()]
    summary = summarise_level("baseline", 4, results, wall_s=10.0)
    assert (summary.requests, summary.ok, summary.errors) == (4, 3, 1)
    assert summary.ttft_p50_s == pytest.approx(0.4)
    assert summary.ttft_p95_s is None, "round 2: no p95 for fewer than 20 successful requests"
    assert summary.ttft_max_s == pytest.approx(0.6)
    assert summary.output_tokens_per_request_mean == pytest.approx(200.0)
    assert summary.total_p50_s == pytest.approx(5.0)
    assert summary.request_tokens_per_s_p50 == pytest.approx(40.0)
    assert summary.decode_tokens_per_s_p50 == pytest.approx(45.0)
    assert summary.output_tokens_total == 600
    assert summary.aggregate_tokens_per_s == pytest.approx(60.0)  # failed requests add time but no tokens
    assert summary.tokens_source == "usage"


def test_level_summary_when_every_request_failed():
    summary = summarise_level("baseline", 2, [bad(), bad()], wall_s=1.0)
    assert summary.ok == 0 and summary.errors == 2
    assert summary.ttft_p50_s is None and summary.aggregate_tokens_per_s is None
    assert summary.tokens_source == "none"


def test_level_summary_reports_mixed_token_sources():
    chunky = good(0.2, 4.0, 100)
    chunky.tokens_source = "chunks"
    summary = summarise_level("x", 1, [good(0.2, 4.0, 100), chunky], wall_s=8.0)
    assert summary.tokens_source == "chunks+usage"


def test_csv_rows_have_exactly_the_declared_columns():
    result = good(0.25, 4.0, 200, 50.0)
    row = streamstats.request_row("baseline", 4, 7, result)
    assert list(row.keys()) == streamstats.REQUEST_COLUMNS
    assert row["ttft_s"] == "0.2500" and row["request_tokens_per_s"] == "50.0000"
    assert row["concurrency"] == 4 and row["request_index"] == 7 and row["ok"] is True
    failed_row = streamstats.request_row("baseline", 4, 8, bad())
    assert failed_row["ttft_s"] == "" and failed_row["error"].startswith("ThrottlingException")
    summary = summarise_level("baseline", 4, [result], wall_s=4.0)
    srow = streamstats.summary_row(summary)
    assert list(srow.keys()) == streamstats.SUMMARY_COLUMNS
    assert srow["aggregate_tokens_per_s"] == "50.0000"


def test_summary_table_shows_the_numbers():
    summary = summarise_level("baseline", 4, [good(0.25, 4.0, 200, 50.0)], wall_s=4.0)
    table = streamstats.format_summary_table([summary])
    assert "TTFT p50 s" in table and "0.250" in table and "50.00" in table and "1/1" in table
