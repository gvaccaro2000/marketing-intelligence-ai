"""Post a Slack mrkdwn message to the incoming webhook in $SLACK_WEBHOOK_URL.

Usage:
  python scripts/post_to_slack.py reports/weekly_ua_2026-08-17.slack
  echo "*hello*" | python scripts/post_to_slack.py -
  python scripts/post_to_slack.py --dry-run FILE     # print the JSON payload, don't send

The webhook URL is a secret: it is never printed, logged or included in error messages.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

MAX_CHARS = 3900  # Slack truncates long `text` messages; keep weekly posts short


def ssl_context() -> ssl.SSLContext:
    cafile = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    return ssl.create_default_context(cafile=cafile if cafile and os.path.exists(cafile) else None)


def redact(msg: str, url: str) -> str:
    return msg.replace(url, "<SLACK_WEBHOOK_URL>") if url else msg


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="file with the mrkdwn message, or - for stdin")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    text = (sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()).strip()
    if not text:
        print("error: empty message", file=sys.stderr)
        return 2
    if len(text) > MAX_CHARS:
        print(f"error: message is {len(text)} chars (max {MAX_CHARS}); shorten it", file=sys.stderr)
        return 2

    payload = json.dumps({"text": text, "mrkdwn": True}).encode()
    if args.dry_run:
        print(payload.decode())
        return 0

    url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url:
        print("error: SLACK_WEBHOOK_URL is not set", file=sys.stderr)
        return 2
    if not url.startswith("https://hooks.slack.com/"):
        print("error: SLACK_WEBHOOK_URL is not a Slack incoming-webhook URL", file=sys.stderr)
        return 2

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=ssl_context()) as resp:
            body = resp.read().decode(errors="replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"error: Slack returned HTTP {e.code}: {redact(body, url)[:200]}", file=sys.stderr)
        return 1
    except Exception as e:  # network/TLS errors may embed the URL; never echo it
        print(f"error: post failed ({type(e).__name__}): {redact(str(e), url)[:200]}", file=sys.stderr)
        return 1

    if status != 200 or body.strip() != "ok":
        print(f"error: unexpected Slack response HTTP {status}: {redact(body, url)[:200]}", file=sys.stderr)
        return 1
    print(f"posted to Slack ({len(text)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
