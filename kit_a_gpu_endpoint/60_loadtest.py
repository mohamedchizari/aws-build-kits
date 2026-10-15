#!/usr/bin/env python3
"""60_loadtest.py: measure the endpoint at a few concurrency levels and write the numbers to CSV.

For each level C, C workers send streamed requests back to back until --requests-per-level requests
have finished (a closed loop: a worker sends its next request as soon as its last one ends). For every
request the script records time to first token and output tokens; for every level it records the
aggregate output tokens per second. The exact definitions are at the top of streamstats.py and that
logic is unit-tested offline.

Warm-up, not recorded: one request before anything else, then, before each level, C requests sent at the
same moment. They open one connection per worker, so that no recorded request carries a TCP and TLS
handshake inside its time to first token. The summary CSV has the count in the column warmup_requests.
This assumes the HTTP client keeps the connections open between the warm-up and the level, which is
what it did against a local test server; it was not checked against AWS.

Also printed and written for each level: output tokens per request (mean, min, max). Without --ignore-eos a
request may stop before --max-tokens, so say "up to" that number and quote the mean. TTFT p95 is given only
for a level with at least 20 successful requests; below that the column shows "-". The decode rate counts
stream chunks, not the server's token count; the script says so when the two counts differ.

If the model sends reasoning text ("thinking"), time to first token is the time to the first reasoning
token. The script warns when it sees that, and the CSV files count it (reasoning_seen, reasoning_requests).

If .state.json records a deploy in another Region, account or prefix than this shell points at, the
script stops and says so. An exported AWS_REGION overrides config.env.

Two files are written to results/:
  loadtest_<label>_<UTC time>_requests.csv   one row per request
  loadtest_<label>_<UTC time>_summary.csv    one row per concurrency level  (these are the numbers to quote)

Ctrl-C: no further request is sent. The script waits for the requests already on their way (at most one
per worker, for at most 60 seconds), writes what it measured to two files whose names carry INTERRUPTED,
prints the BILLING lines and exits 130. A level that was cut short has its finished requests in the
per-request file and no row in the summary file: an aggregate over a cut level is not comparable.

Run it once with --label baseline, change one setting with 70_change_one_setting.py, then run it
again with --label changed and compare the two summary files.

Creates no AWS resource. The endpoint is already billing by the hour.
Never run against AWS by the author of this kit: there was no AWS account. See README section 8.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import kitlib
import streamstats
from kitlib import Aws, Config
from streamstats import LevelSummary, RequestResult

DEFAULT_PROMPT = (
    "Write a detailed, numbered checklist for shutting down a cloud GPU endpoint safely, "
    "with a short explanation for each step. Use at least twelve steps."
)


REASONING_WARNING = ("WARNING: the model sent reasoning text (\"thinking\"). Time to first token is then the time to the "
                     "first REASONING token, not to the first word of the answer, and output tokens include the "
                     "reasoning. CHAT_TEMPLATE_KWARGS_JSON did not switch thinking off on this container "
                     "(README section 8, unverified item 7). Say so next to any number you quote.")


def parse_levels(text: str) -> list[int]:
    try:
        levels = [int(part) for part in text.split(",") if part.strip()]
    except ValueError as exc:
        raise kitlib.KitError(f"--concurrency must be whole numbers separated by commas, for example 1,4,16 ({exc}).") from exc
    if not levels or any(level < 1 or level > 64 for level in levels):
        raise kitlib.KitError("--concurrency needs at least one level, each between 1 and 64.")
    return levels


def request_body(cfg: Config, prompt: str, max_tokens: int, ignore_eos: bool) -> dict[str, Any]:
    """Streamed Chat Completions body. Field sources are listed in 50_invoke.chat_body and streamstats.py."""
    body: dict[str, Any] = {
        "model": cfg.hf_model_id,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if cfg.chat_template_kwargs:
        body["chat_template_kwargs"] = cfg.chat_template_kwargs
    if ignore_eos:
        # ignore_eos is a vLLM extension (vLLM v0.30.0 ChatCompletionRequest, read 2026-10-07): every request
        # then generates exactly max_tokens tokens, which makes levels easier to compare.
        # UNVERIFIED: that the AWS container passes ignore_eos (and stream_options, chat_template_kwargs above)
        # through to vLLM on /invocations. vLLM request fields, read in vLLM source, not in an AWS doc. Check the
        # output_tokens column: with ignore_eos every row should equal max_tokens.
        body["ignore_eos"] = True
    return body


def failed_result(error: str, total_s: float) -> RequestResult:
    return RequestResult(ok=False, error=error[:300], ttft_s=None, total_s=max(0.0, total_s), output_tokens=0,
                         tokens_source="none", prompt_tokens=None, request_tokens_per_s=None,
                         decode_tokens_per_s=None, text_chunks=0, finish_reason="", saw_done=False)


def make_sender(aws: Aws, endpoint_name: str, body: dict[str, Any],
                clock: Callable[[], float] = time.perf_counter) -> Callable[[int], RequestResult]:
    """Return a function that sends one streamed request and measures it. Never raises."""
    payload = json.dumps(body).encode("utf-8")

    def send(index: int) -> RequestResult:  # noqa: ARG001 - index is for callers that want it
        started = clock()
        try:
            # InvokeEndpointWithResponseStream:
            # https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_runtime_InvokeEndpointWithResponseStream.html (read 2026-10-07)
            response = aws.call("sagemaker-runtime", "invoke_endpoint_with_response_stream",
                                EndpointName=endpoint_name, ContentType="application/json", Body=payload)
        except Exception as exc:  # noqa: BLE001 - a failed request is data, not a crash
            code = kitlib.error_code(exc)
            return failed_result(f"{code or type(exc).__name__}: {kitlib.error_message(exc)}", clock() - started)
        if response is None:  # dry run: the call was printed, not made
            return failed_result("dry run", 0.0)
        return streamstats.consume_event_stream(response["Body"], clock, started)

    return send


INTERRUPT_GRACE_S = 60.0  # after Ctrl-C: how long to wait for the requests that are already on their way


class LevelInterrupted(Exception):
    """Ctrl-C arrived while a level was running. Carries what had finished by then."""

    def __init__(self, results: list[RequestResult], wall: float, sent: int, abandoned: int):
        super().__init__("interrupted")
        self.results, self.wall, self.sent, self.abandoned = results, wall, sent, abandoned


def run_level(send: Callable[[int], RequestResult], concurrency: int, requests: int,
              clock: Callable[[], float] = time.perf_counter) -> tuple[list[RequestResult], float]:
    """Closed loop: `concurrency` workers share a counter and stop when `requests` have been sent.

    On Ctrl-C the workers take no further request. The requests already sent are given INTERRUPT_GRACE_S
    seconds to finish (a second Ctrl-C ends the wait), and LevelInterrupted is raised with the finished ones.
    The workers are daemon threads, so a request that never returns cannot keep the script alive.
    """
    results: list[RequestResult | None] = [None] * requests
    lock = threading.Lock()
    stop = threading.Event()
    next_index = 0
    in_flight = 0

    def worker() -> None:
        nonlocal next_index, in_flight
        while True:
            with lock:
                if stop.is_set() or next_index >= requests:
                    return
                index = next_index
                next_index += 1
                in_flight += 1
            started_at = clock()
            try:
                results[index] = send(index)
            except Exception as exc:  # noqa: BLE001 - send() is written never to raise; if it does, the request counts
                # as failed instead of leaving the level unseen (round 5, F6: a daemon thread's error reaches no caller).
                results[index] = failed_result(f"{type(exc).__name__} in this kit's measuring code: {kitlib.redact(exc)}",
                                               clock() - started_at)
            finally:
                with lock:
                    in_flight -= 1

    started = clock()
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(concurrency)]
    try:
        for thread in threads:
            thread.start()
        while any(thread.is_alive() for thread in threads):
            for thread in threads:
                thread.join(0.05)
    except KeyboardInterrupt:
        with lock:
            stop.set()  # from here on no worker takes another request, and one not yet started takes none
        print(f"\nCtrl-C: no further request is sent. Waiting up to {INTERRUPT_GRACE_S:g} s for the {in_flight} already "
              "on their way (Ctrl-C again stops the wait)...", file=sys.stderr, flush=True)
        pause = threading.Event()
        try:
            deadline = time.monotonic() + INTERRUPT_GRACE_S
            while in_flight and time.monotonic() < deadline:
                pause.wait(0.02)
        except KeyboardInterrupt:
            pass
        with lock:
            sent, abandoned = next_index, in_flight
            done = [r for r in results if r is not None]
        raise LevelInterrupted(done, clock() - started, sent, abandoned) from None
    wall = clock() - started
    return [r for r in results if r is not None], wall


def write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def run(args: Any, cfg: Config, aws: Aws, out: Callable[[str], None] = print,
        clock: Callable[[], float] = time.perf_counter,
        sender_factory: Callable[..., Callable[[int], RequestResult]] = make_sender) -> int:
    levels = parse_levels(args.concurrency)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", args.label):
        raise kitlib.KitError("--label may contain letters, digits, hyphen and underscore, at most 40 characters.")
    if args.requests_per_level < 1 or args.requests_per_level > 2000:
        raise kitlib.KitError("--requests-per-level must be between 1 and 2000.")
    state = kitlib.load_state(args.state_path)
    kitlib.require_state_matches(state, cfg, kitlib.caller_account(aws), args.state_path.name)
    now = kitlib.utc_now()
    if kitlib.past_deadline(state, now) and not args.ignore_deadline and not aws.dry_run:
        for line in kitlib.billing_lines(state, now):
            out(line)
        raise kitlib.KitError("You are past the teardown time you set. Tear down, or pass --ignore-deadline "
                              "if you have decided to keep paying.")

    endpoint_name = args.endpoint_name or cfg.endpoint_name
    body = request_body(cfg, args.prompt, args.max_tokens, args.ignore_eos)
    deployed_env = ((state or {}).get("deploy") or {}).get("env", {})
    out(f"Load test '{args.label}' against {endpoint_name} in {cfg.region}.")
    out(f"Levels {levels}, {args.requests_per_level} requests per level, max_tokens {args.max_tokens}, "
        f"ignore_eos {args.ignore_eos}.")
    if deployed_env:
        out("Deployed settings: " + ", ".join(f"{k}={v}" for k, v in sorted(deployed_env.items())))
    out("The client is this machine. Time to first token includes the network path from here to the Region.")
    out("It should not include opening a connection: warm-up requests that are not recorded do that first "
        "(seen against a local test server, not checked against AWS).")

    send = sender_factory(aws, endpoint_name, body, clock)
    if aws.dry_run:
        send(0)
        recorded = sum(max(args.requests_per_level, level) for level in levels)
        warm_ups = 1 + sum(levels)
        out(f"DRY RUN: that call would be made about {recorded + warm_ups} times: {warm_ups} warm-up requests that "
            f"are not recorded (1 first, then one per worker before each level), and {recorded} recorded "
            f"({args.requests_per_level} per level). 0 made. No CSV written.")
        return 0

    out("Warm-up request (not recorded)...")
    warm = send(-1)
    if not warm.ok:
        # The endpoint on record is billing whether or not it answers, so the reminder comes before the stop.
        for line in kitlib.billing_lines(state, kitlib.utc_now()):
            out(line)
        raise kitlib.KitError(f"The warm-up request failed, so no load was sent: {kitlib.redact(warm.error)}. "
                              "This script created and deleted nothing. Look at the endpoint with "
                              "python 55_observe.py; an endpoint that exists is billing: python 90_teardown.py")
    out(f"  ok: time to first token {warm.ttft_s:.3f} s, {warm.output_tokens} tokens (counted from: {warm.tokens_source}).")
    if warm.reasoning_seen:
        out(REASONING_WARNING)

    request_rows: list[dict[str, Any]] = []
    summaries: list[LevelSummary] = []

    def record(level: int, results: list[RequestResult]) -> None:
        for index, result in enumerate(results):
            row = streamstats.request_row(args.label, level, index, result)
            row["error"] = kitlib.redact(row["error"])  # AWS error text can name the caller; the file is kept
            request_rows.append(row)

    interrupted = ""
    for level in levels:
        if interrupted:
            break
        count = max(args.requests_per_level, level)
        # Not recorded: `level` requests at once, so each worker's connection is open before the recorded run.
        # UNVERIFIED: that botocore keeps those connections open and reuses them for the recorded requests when
        # the server is SageMaker. It did against a local test server (one connection per worker, none opened
        # during the recorded run); nothing here was run against AWS. If AWS closes idle connections quickly,
        # some recorded requests still include a handshake in their time to first token.
        try:
            warm_results, _ = run_level(send, level, level, clock)
        except LevelInterrupted:
            interrupted = f"during the warm-up of level {level}; that level has no recorded request"
            break
        warm_failed = sum(1 for r in warm_results if not r.ok)
        out(f"Level {level}: {level} warm-up request(s) sent (not recorded"
            f"{', ' + str(warm_failed) + ' failed' if warm_failed else ''}); now sending {count} recorded requests...")
        try:
            results, wall = run_level(send, level, count, clock)
        except LevelInterrupted as cut:
            record(level, cut.results)
            interrupted = (f"in level {level} after {cut.sent} of {count} recorded requests were sent: {len(cut.results)} "
                           "finished and are in the per-request file"
                           + (f", {cut.abandoned} did not come back in time and are in no file" if cut.abandoned else "")
                           + "; that level has NO row in the summary file")
            break
        summary = streamstats.summarise_level(args.label, level, results, wall, warmup_requests=level)
        summaries.append(summary)
        record(level, results)
        if summary.errors:
            first_error = next((r.error for r in results if not r.ok), "")
            out(f"  {summary.errors} of {summary.requests} failed. First error: {kitlib.redact(first_error)}")
        if summary.ok:
            out(f"  Level {level}: {summary.ok} OK request(s), output tokens per request: mean "
                f"{summary.output_tokens_per_request_mean:.1f}, min {summary.output_tokens_min}, max "
                f"{summary.output_tokens_max} (each request could generate up to {args.max_tokens}; counted from: "
                f"{summary.tokens_source}).")

    stamp = kitlib.utc_now().strftime("%Y%m%dT%H%M%SZ") + ("_INTERRUPTED" if interrupted else "")
    requests_path = args.results_dir / f"loadtest_{args.label}_{stamp}_requests.csv"
    summary_path = args.results_dir / f"loadtest_{args.label}_{stamp}_summary.csv"
    write_csv(requests_path, streamstats.REQUEST_COLUMNS, request_rows)
    write_csv(summary_path, streamstats.SUMMARY_COLUMNS, [streamstats.summary_row(s) for s in summaries])

    out("")
    if summaries:
        out(streamstats.format_summary_table(summaries))
        out("")
    out(f"Per-request rows: {requests_path}")
    out(f"Summary rows:     {summary_path}")
    if any(s.tokens_source != "usage" for s in summaries if s.ok):
        out("NOTE: some token counts came from counting stream chunks, not from the server's usage field. "
            "Say 'approximately' when you quote tokens per second from those rows.")
    small = [s.concurrency for s in summaries if s.ok and s.ttft_p95_s is None]
    if small:
        out(f"NOTE: TTFT p95 is shown as '-' for level(s) {', '.join(str(c) for c in small)}: fewer than "
            f"{streamstats.MIN_REQUESTS_FOR_P95} successful requests, and a p95 of so few is the maximum under another "
            "name. ttft_max_s is in the summary CSV. Use --requests-per-level 20 or more to get a p95.")
    mismatched = sum(s.token_chunk_mismatch_requests for s in summaries)
    if mismatched:
        out(f"NOTE: decode tok/s counts stream chunks, not the server's token count. In {mismatched} of "
            f"{sum(s.ok for s in summaries)} successful requests the two counts differed (columns output_tokens and "
            "text_chunks in the per-request CSV). Where the server counted more tokens than chunks arrived, the true "
            "token rate is higher than the decode column. Quote the decode column as chunks per second, or leave it out.")
    reasoning = sum(s.reasoning_requests for s in summaries)
    if reasoning:
        out(f"{reasoning} recorded request(s) carried reasoning text. " + REASONING_WARNING)
    for line in kitlib.billing_lines(state, kitlib.utc_now()):
        out(line)
    if interrupted:
        out(f"INTERRUPTED by Ctrl-C {interrupted}. {len(summaries)} of {len(levels)} level(s) finished and are in the "
            "summary file; the file names say INTERRUPTED. Nothing was deleted: the endpoint is still billing. "
            "To stop the charge: python 90_teardown.py")
        return 130
    total_errors = sum(s.errors for s in summaries)
    return 0 if total_errors == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = kitlib.base_parser(__doc__ or "")
    parser.add_argument("--concurrency", default="1,4,16", help="Comma-separated levels (default 1,4,16).")
    parser.add_argument("--requests-per-level", type=int, default=32,
                        help="Requests per level (default 32; a level never sends fewer requests than its concurrency).")
    parser.add_argument("--max-tokens", type=int, default=200)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--label", default="baseline", help="Goes into the file names and the CSV (default baseline).")
    parser.add_argument("--ignore-eos", action="store_true",
                        help="Ask vLLM to generate exactly --max-tokens tokens per request.")
    parser.add_argument("--endpoint-name", default=None, help="Default: <KIT_PREFIX>-kita-endpoint.")
    parser.add_argument("--ignore-deadline", action="store_true", help="Run even though your teardown time has passed.")
    args = parser.parse_args(argv)
    args.state_path = kitlib.STATE_FILE
    args.results_dir = kitlib.RESULTS_DIR
    cfg = kitlib.load_config()
    levels = parse_levels(args.concurrency)
    client_config = {"sagemaker-runtime": {
        # One connection per worker, no automatic retries (a retry would hide a slow or failed request),
        # and a read timeout long enough for a queued request.
        "max_pool_connections": max(levels) + 2,
        "retries": {"total_max_attempts": 1},
        "read_timeout": 300,
        "connect_timeout": 10,
    }}
    return run(args, cfg, Aws(cfg.region, args.dry_run, client_config=client_config))


if __name__ == "__main__":
    sys.exit(kitlib.guarded(main))
