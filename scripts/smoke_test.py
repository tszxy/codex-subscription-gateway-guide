#!/usr/bin/env python3
"""Send exactly one small Responses request. This consumes real upstream usage."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Host origin, without /v1")
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    key = os.environ.get("GATEWAY_KEY", "")
    if not key:
        parser.error("Set GATEWAY_KEY in your environment; do not pass a key on the command line.")
    base = args.base_url.rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.path or \
            parsed.query or parsed.fragment or parsed.username or parsed.password:
        parser.error("base-url must be an http(s) host origin without path, query or credentials")
    if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        parser.error("Use HTTPS for non-loopback gateways")
    body = json.dumps({"model": args.model, "input": "Reply only OK.",
                       "reasoning": {"effort": "medium"}, "stream": False}).encode()
    request = urllib.request.Request(base + "/v1/responses", data=body, headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json",
    })
    # Do not send a bearer key to a redirect destination.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect())
    print("Sending ONE real request; no retries. model=" + args.model)
    try:
        with opener.open(request, timeout=180) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            data = json.loads(error.read())
            detail = data.get("error", {}) if isinstance(data, dict) else {}
            code = detail.get("code", "unknown") if isinstance(detail, dict) else "unknown"
        except (ValueError, UnicodeDecodeError):
            code = "non_json_response"
        print(f"FAILED status={error.code} code={code}; no automatic retry", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, ValueError):
        print("FAILED network/timeout/response; no automatic retry", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print("FAILED unexpected response shape", file=sys.stderr)
        return 1
    print(json.dumps({"id": data.get("id"), "model": data.get("model"),
                      "status": data.get("status"), "usage": data.get("usage")}, ensure_ascii=False))
    outputs = data.get("output", [])
    has_output = isinstance(outputs, list) and bool(outputs)
    if data.get("error") or data.get("status") != "completed" or not has_output:
        print("FAILED response not completed or has no output; inspect privately", file=sys.stderr)
        return 1
    print("PASS: completed Responses request; tool calling is not tested here")
    return 0


if __name__ == "__main__":
    sys.exit(main())

