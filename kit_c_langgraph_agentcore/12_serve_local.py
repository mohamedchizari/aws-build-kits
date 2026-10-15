#!/usr/bin/env python3
"""12_serve_local.py: serve the AgentCore entrypoint on this machine, port 8080.

This is the local test AWS documents for a runtime agent: start the app, then
POST to /invocations. It proves the HTTP contract (POST /invocations and
GET /ping on port 8080) before anything is deployed.

Usage:
    python 12_serve_local.py --fake-model --self-test     # no AWS at all; starts, calls itself, stops
    python 12_serve_local.py --fake-model                 # serve until Ctrl-C; then in another terminal:
        curl -s http://localhost:8080/ping
        curl -s -X POST http://localhost:8080/invocations -H "Content-Type: application/json" \\
             -d '{"prompt": "final rules about energy storage"}'
    python 12_serve_local.py --i-understand-this-bills    # real Bedrock model, billed per token
    python 12_serve_local.py --dry-run
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.request

import kitlib

HOST = "127.0.0.1"


def _free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((HOST, port)) != 0


def _http(method: str, url: str, body: dict | None = None, timeout: float = 120) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    # a local address must not be sent through an HTTP proxy
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def self_test(port: int, prompt: str, out=print) -> int:
    import uvicorn

    import agentcore_app

    server = uvicorn.Server(uvicorn.Config(agentcore_app.app, host=HOST, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started:
            if time.monotonic() > deadline:
                out("The server did not start within 20 seconds.")
                return 1
            time.sleep(0.1)
        status, ping = _http("GET", f"http://{HOST}:{port}/ping")
        out(f"GET /ping -> {status} {json.dumps(ping)}")
        started = time.perf_counter()
        status2, body = _http("POST", f"http://{HOST}:{port}/invocations", {"prompt": prompt})
        seconds = time.perf_counter() - started
        out(f"POST /invocations -> {status2} in {seconds:.2f}s")
        out(json.dumps(body, indent=2, ensure_ascii=False)[:3000])
        ok = (status == 200 and ping.get("status") == "Healthy" and status2 == 200
              and "result" in body and "grounding" in body)
        out("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
        return 0 if ok else 1
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def main(argv: list[str] | None = None, out=print) -> int:
    parser = kitlib.make_parser(__doc__, bills=True)
    parser.add_argument("--fake-model", action="store_true",
                        help="scripted fake model: no AWS call, no token cost")
    parser.add_argument("--self-test", action="store_true",
                        help="start the server, call /ping and /invocations once, stop")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--prompt", default="final rules about energy storage")
    args = parser.parse_args(argv)
    cfg = kitlib.Config.from_env()

    if args.dry_run:
        out(f"DRY-RUN  would serve agentcore_app.app on http://{HOST}:{args.port} "
            "(POST /invocations, GET /ping)")
        if args.fake_model:
            out("DRY-RUN  fake model: no AWS call would be made")
        else:
            out(f"DRY-RUN  would call bedrock-runtime.converse(modelId={cfg.model_id!r}, ...) in "
                f"{cfg.region} once per model turn of each request")
        out("DRY-RUN  would call GET https://www.federalregister.gov/api/v1/... per tool call")
        return 0

    if args.fake_model:
        os.environ["KIT_FAKE_MODEL"] = "1"
    else:
        if not kitlib.confirm_billing(args, kitlib.PRICE_LINES_MODEL, out):
            return 2
        os.environ.pop("KIT_FAKE_MODEL", None)
        os.environ.setdefault("MODEL_ID", cfg.model_id)
        os.environ.setdefault("KIT_BEDROCK_REGION", cfg.region)

    if not _free(args.port):
        out(f"Port {args.port} is already in use. Stop whatever is using it, or pass --port.")
        return 1
    if args.self_test:
        return self_test(args.port, args.prompt, out)

    import agentcore_app

    os.environ.pop("KIT_BIND_HOST", None)  # a local server stays on the loopback address
    out(f"Serving on http://{HOST}:{args.port}  (Ctrl-C to stop)")
    agentcore_app.app.run(port=args.port, host=HOST)
    return 0


if __name__ == "__main__":
    kitlib.script_main(main)
