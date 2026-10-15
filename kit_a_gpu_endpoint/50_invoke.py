#!/usr/bin/env python3
"""50_invoke.py: call the endpoint three ways and watch what comes back.

  plain    InvokeEndpoint. One JSON request, one JSON response after generation has finished.
  stream   InvokeEndpointWithResponseStream. Text arrives while it is generated. Prints time to first token.
  openai   The OpenAI Python SDK pointed at the endpoint's /openai/v1 path with a short-lived bearer token.

Before anything is timed, each client (boto3 for plain and stream, the OpenAI SDK for openai) sends one
1-token request that is not timed. It opens the connection, so the timed calls do not include the TCP and
TLS handshake and the three modes can be compared. "Time to first token" means the same thing in the stream
and openai modes: the first generated text of any kind, answer or reasoning.

If .state.json records a deploy in another Region, account or prefix than this shell points at, the
script stops and says so. An exported AWS_REGION overrides config.env.

Creates nothing. The endpoint is already billing by the hour; these calls add only data-transfer cents.
Never run against AWS by the author of this kit: there was no AWS account. See README section 8.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from typing import Any, Callable

import kitlib
import streamstats
from kitlib import Aws, Config

DEFAULT_PROMPT = "In four sentences, explain why a GPU endpoint costs money while it is idle."


def chat_body(cfg: Config, prompt: str, max_tokens: int, stream: bool) -> dict[str, Any]:
    """Chat Completions request body, as the AWS vLLM container expects on /invocations.

    Shape (model, messages, max_tokens) as in the AWS example:
    https://aws.github.io/deep-learning-containers/vllm/deployment/sagemaker/ (read 2026-10-07).
    "model" is the served model name, which equals SM_VLLM_MODEL.
    stream, stream_options.include_usage and chat_template_kwargs are fields of vLLM's ChatCompletionRequest
    (vLLM v0.30.0, vllm/entrypoints/openai/chat_completion/protocol.py, read 2026-10-07).
    """
    # UNVERIFIED: that the AWS container passes stream_options and chat_template_kwargs through to vLLM unchanged
    # on /invocations, and that {"enable_thinking": false} switches Qwen3's reasoning off there. They are vLLM
    # request fields, read in vLLM source, not in an AWS doc. The scripts warn when reasoning text still arrives.
    body: dict[str, Any] = {
        "model": cfg.hf_model_id,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    if cfg.chat_template_kwargs:
        body["chat_template_kwargs"] = cfg.chat_template_kwargs
    if stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    return body


REASONING_WARNING = ("WARNING: the model sent reasoning text (\"thinking\"). Time to first token above is the time to "
                     "the first REASONING token, not to the first word of the answer, and the answer tokens include "
                     "the reasoning. CHAT_TEMPLATE_KWARGS_JSON did not switch thinking off on this container "
                     "(README section 8, unverified item 7). Say so next to any number you quote.")


def warm_up(aws: Aws, cfg: Config, endpoint_name: str, out: Callable[[str], None]) -> None:
    """One 1-token request that is not timed, so the timed boto3 calls reuse an open connection."""
    # UNVERIFIED: that the timed calls reuse the connection this request opens (same boto3 client, same host).
    # That is how botocore's connection pool behaved against a local test server; it was not checked against AWS.
    out("--- warm-up (not timed): one 1-token InvokeEndpoint request to open the connection ---")
    body = chat_body(cfg, "Say OK.", 1, stream=False)
    # InvokeEndpoint: https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_runtime_InvokeEndpoint.html (read 2026-10-07)
    response = aws.call("sagemaker-runtime", "invoke_endpoint", EndpointName=endpoint_name,
                        ContentType="application/json", Body=json.dumps(body).encode("utf-8"))
    if response is not None:
        response["Body"].read()  # read to the end so the connection goes back to the pool


def invoke_plain(aws: Aws, cfg: Config, endpoint_name: str, prompt: str, max_tokens: int,
                 out: Callable[[str], None], clock: Callable[[], float]) -> bool:
    body = chat_body(cfg, prompt, max_tokens, stream=False)
    out("--- plain: sagemaker-runtime InvokeEndpoint ---")
    started = clock()
    # InvokeEndpoint: https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_runtime_InvokeEndpoint.html (read 2026-10-07)
    response = aws.call("sagemaker-runtime", "invoke_endpoint", EndpointName=endpoint_name,
                        ContentType="application/json", Body=json.dumps(body).encode("utf-8"))
    if response is None:
        return True
    payload = json.loads(response["Body"].read())
    elapsed = clock() - started
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        out(f"Unexpected response shape: {json.dumps(payload)[:600]}")
        return False
    usage = payload.get("usage") or {}
    out(text.strip())
    out(f"[plain] {elapsed:.2f} s for the whole answer. Nothing was visible until the end. "
        f"completion_tokens={usage.get('completion_tokens')}, prompt_tokens={usage.get('prompt_tokens')}")
    return True


def invoke_stream(aws: Aws, cfg: Config, endpoint_name: str, prompt: str, max_tokens: int,
                  out: Callable[[str], None], clock: Callable[[], float],
                  write: Callable[[str], None] | None = None) -> bool:
    body = chat_body(cfg, prompt, max_tokens, stream=True)
    out("--- stream: sagemaker-runtime InvokeEndpointWithResponseStream ---")
    started = clock()
    # InvokeEndpointWithResponseStream:
    # https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_runtime_InvokeEndpointWithResponseStream.html (read 2026-10-07)
    # The response Body is an event stream of PayloadPart events; the AWS CLI cannot do this call
    # (https://docs.aws.amazon.com/sagemaker/latest/dg/realtime-endpoints-test-endpoints.html, read 2026-10-07).
    response = aws.call("sagemaker-runtime", "invoke_endpoint_with_response_stream", EndpointName=endpoint_name,
                        ContentType="application/json", Body=json.dumps(body).encode("utf-8"))
    if response is None:
        return True
    result = streamstats.consume_event_stream(response["Body"], clock, started, on_text=write)
    if write is not None:
        write("\n")
    if not result.ok:
        out(f"[stream] FAILED: {result.error}")
        return False
    decode = "-" if result.decode_tokens_per_s is None else f"{result.decode_tokens_per_s:.1f}"
    out(f"[stream] time to first token {result.ttft_s:.3f} s, total {result.total_s:.2f} s, "
        f"{result.output_tokens} output tokens (counted from: {result.tokens_source}), "
        f"{result.text_chunks} text chunks, {decode} chunks/s after the first chunk "
        "(that is tokens/s when one chunk is one token).")
    if result.reasoning_seen:
        out(REASONING_WARNING)
    return True


def openai_delta_text(delta: Any) -> tuple[str, bool]:
    """(generated text in this SDK chunk, whether any of it is reasoning).

    Same definition as streamstats.delta_text, so the openai mode and the stream mode time the same thing:
    answer text ("content") and reasoning text ("reasoning", or the older "reasoning_content") both count.
    """
    fields = {key: getattr(delta, key, None) for key in ("content", "reasoning", "reasoning_content")}
    text = streamstats.delta_text({"choices": [{"delta": fields}]})
    reasoning = any(isinstance(fields[key], str) and fields[key] for key in ("reasoning", "reasoning_content"))
    return text, bool(reasoning)


def invoke_openai(cfg: Config, endpoint_name: str, prompt: str, max_tokens: int, dry_run: bool,
                  out: Callable[[str], None], clock: Callable[[], float],
                  write: Callable[[str], None] | None = None) -> bool:
    """OpenAI-compatible path.

    Confirmed on https://docs.aws.amazon.com/sagemaker/latest/dg/realtime-endpoints-openai-compatible.html and
    https://aws.amazon.com/blogs/machine-learning/announcing-openai-compatible-api-support-for-amazon-sagemaker-ai-endpoints/
    (blog dated 20 May 2026; both read 2026-10-07):
      base URL  https://runtime.sagemaker.<REGION>.amazonaws.com/endpoints/<ENDPOINT_NAME>/openai/v1
      auth      bearer token from sagemaker.core.token_generator.generate_token(region=..., expiry=timedelta(...)),
                made locally from your AWS credentials; valid for at most 12 hours
      IAM       sagemaker:InvokeEndpoint on the endpoint and sagemaker:CallWithBearerToken on "*"
      supported the SageMaker vLLM container, Chat Completions, streaming
    """
    base_url = f"https://runtime.sagemaker.{cfg.region}.amazonaws.com/endpoints/{endpoint_name}/openai/v1"
    out("--- openai: OpenAI SDK against the endpoint's /openai/v1 path ---")
    if dry_run:
        out(f"DRY-RUN would POST {base_url}/chat/completions twice with a 5-minute bearer token "
            "(the token is never printed): one 1-token warm-up request that is not timed, then the timed "
            "request with stream=true. No boto3 call is involved.")
        return True
    try:
        from openai import OpenAI
        from sagemaker.core.token_generator import generate_token
    except ImportError as exc:
        out(f"[openai] SKIPPED: {exc}. Install the two extra packages: python -m pip install -r requirements.txt")
        return False

    # The token is a secret derived from your AWS credentials. Short expiry, never printed, never stored.
    try:
        token = generate_token(region=cfg.region, expiry=dt.timedelta(minutes=5))
    except Exception as exc:  # noqa: BLE001 - the generator raises a plain RuntimeError when it finds no credentials
        out(f"[openai] FAILED before any request: no bearer token could be made ({type(exc).__name__}: {exc}). "
            "The token is made on this machine from your AWS credentials. Sign in first (README section 3).")
        return False
    extra_body = {"chat_template_kwargs": cfg.chat_template_kwargs} if cfg.chat_template_kwargs else None
    first_at: float | None = None
    completion_tokens: int | None = None
    reasoning_seen = False
    head = ""
    # UNVERIFIED: passing the Hugging Face id as "model" on the /openai/v1 path. AWS examples pass an empty string
    # and say the field "is passed through to the container as-is"; vLLM serves the model under SM_VLLM_MODEL.
    # stream_options and chat_template_kwargs are vLLM request fields (see chat_body), not confirmed in an AWS doc.
    try:
        client = OpenAI(base_url=base_url, api_key=token)
        # Not timed: one 1-token request that opens this client's connection (TCP and TLS handshake).
        client.chat.completions.create(model=cfg.hf_model_id, messages=[{"role": "user", "content": "Say OK."}],
                                       max_tokens=1, extra_body=extra_body)
        started = clock()
        stream = client.chat.completions.create(
            model=cfg.hf_model_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.7,
            stream=True,
            stream_options={"include_usage": True},
            extra_body=extra_body,
        )
        for chunk in stream:
            if getattr(chunk, "usage", None) is not None:
                completion_tokens = chunk.usage.completion_tokens
            if not chunk.choices:
                continue
            piece, is_reasoning = openai_delta_text(chunk.choices[0].delta)
            if piece:
                if first_at is None:
                    first_at = clock()
                reasoning_seen = reasoning_seen or is_reasoning
                if len(head) < 16:
                    head += piece
                if write is not None:
                    write(piece)
        total = clock() - started
    except Exception as exc:  # noqa: BLE001 - the SDK's errors carry an HTTP response object, not a boto3-style dict
        if write is not None:
            write("\n")
        # str(exc) carries the HTTP status and the body AWS sent. The token is cut out in case a library echoes it.
        out(f"[openai] FAILED: {type(exc).__name__}: {str(exc).replace(token, '<token>')}")
        return False
    if write is not None:
        write("\n")
    if first_at is None:
        out("[openai] FAILED: the stream ended without any text.")
        return False
    out(f"[openai] time to first token {first_at - started:.3f} s, total {total:.2f} s, "
        f"completion_tokens={completion_tokens}. Same model, same endpoint, different front door.")
    if reasoning_seen or head.lstrip().startswith(streamstats.THINK_TAG):
        out(REASONING_WARNING)
    return True


def run(args: Any, cfg: Config, aws: Aws, out: Callable[[str], None] = print,
        clock: Callable[[], float] = time.perf_counter, write: Callable[[str], None] | None = None) -> int:
    state = kitlib.load_state(args.state_path)
    kitlib.require_state_matches(state, cfg, kitlib.caller_account(aws), args.state_path.name)
    now = kitlib.utc_now()
    if kitlib.past_deadline(state, now) and not args.ignore_deadline and not aws.dry_run:
        for line in kitlib.billing_lines(state, now):
            out(line)
        raise kitlib.KitError("You are past the teardown time you set. Tear down, or pass --ignore-deadline "
                              "if you have decided to keep paying.")
    endpoint_name = args.endpoint_name or cfg.endpoint_name
    modes = ["plain", "stream", "openai"] if args.mode == "all" else [args.mode]
    results: dict[str, bool] = {}

    def attempt(label: str, call: Callable[[], bool]) -> bool:
        """An error AWS answered with fails this one step and is printed; the other modes still run.
        Anything else (no credentials, no network) is not an answer about this step and stops the script."""
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - classified just below
            if isinstance(exc, kitlib.KitError) or not kitlib.error_code(exc):
                raise
            out(f"[{label}] FAILED: AWS returned {kitlib.error_code(exc)}: {kitlib.error_message(exc)}")
            return False

    if "plain" in modes or "stream" in modes:
        attempt("warm-up", lambda: warm_up(aws, cfg, endpoint_name, out) or True)
        out("")
    for mode in modes:
        if mode == "plain":
            results[mode] = attempt(mode, lambda: invoke_plain(aws, cfg, endpoint_name, args.prompt, args.max_tokens, out, clock))
        elif mode == "stream":
            results[mode] = attempt(mode, lambda: invoke_stream(aws, cfg, endpoint_name, args.prompt, args.max_tokens,
                                                                 out, clock, write))
        else:
            results[mode] = invoke_openai(cfg, endpoint_name, args.prompt, args.max_tokens, aws.dry_run, out, clock, write)
        out("")
    if aws.dry_run:
        out(f"DRY RUN finished: {aws.calls_printed} boto3 call(s) printed, 0 made.")
        return 0
    passed = sum(1 for ok in results.values() if ok)
    out(f"Invocation modes that worked: {passed} of {len(results)} ({', '.join(m for m, ok in results.items() if ok) or 'none'}).")
    for line in kitlib.billing_lines(state, kitlib.utc_now()):
        out(line)
    return 0 if passed == len(results) else 1


def main(argv: list[str] | None = None) -> int:
    parser = kitlib.base_parser(__doc__ or "")
    parser.add_argument("--mode", choices=["plain", "stream", "openai", "all"], default="all")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--max-tokens", type=int, default=200)
    parser.add_argument("--endpoint-name", default=None, help="Default: <KIT_PREFIX>-kita-endpoint.")
    parser.add_argument("--ignore-deadline", action="store_true", help="Run even though your teardown time has passed.")
    args = parser.parse_args(argv)
    args.state_path = kitlib.STATE_FILE
    cfg = kitlib.load_config()

    def write(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    return run(args, cfg, Aws(cfg.region, args.dry_run), write=write)


if __name__ == "__main__":
    sys.exit(kitlib.guarded(main))
