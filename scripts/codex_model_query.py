#!/usr/bin/env python3
"""Forced SSH command. Return only sanitized Codex routing metadata."""
from collections import OrderedDict
import datetime
import json
import os
import re
import signal
import subprocess
import sys


class EventDeduplicator:
    """This merges display rows, not billing/request IDs."""
    def __init__(self, limit=4096):
        if limit < 1:
            raise ValueError("limit must be positive")
        self.seen = OrderedDict()
        self.limit = limit

    def accept(self, event):
        key = (event["time"][:19], event["provider"], event["model"])
        if key in self.seen:
            return False
        self.seen[key] = None
        if len(self.seen) > self.limit:
            self.seen.popitem(last=False)
        return True


def parse(line):
    try:
        entry = json.loads(line)
        if not isinstance(entry, dict):
            return None
        message = entry.get("MESSAGE", "")
        if not isinstance(message, str) or not re.search(r"\bprovider=codex\b", message):
            return None
        match = re.search(r"\bmodel=([A-Za-z0-9_.:/\[\]-]+)", message)
        if not match:
            return None
        timestamp = datetime.datetime.fromtimestamp(
            int(entry["__REALTIME_TIMESTAMP"]) / 1_000_000, datetime.timezone.utc
        ).isoformat()
        return {"time": timestamp, "provider": "codex", "model": match.group(1)}
    except (ValueError, TypeError, KeyError, OverflowError, OSError):
        return None


def main():
    signal.signal(signal.SIGHUP, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    mode = os.environ.get("SSH_ORIGINAL_COMMAND", "").strip()
    if mode not in ("recent", "watch"):
        print(json.dumps({"error": "Only recent or watch is allowed."}), flush=True)
        return 2
    args = ["journalctl", "-u", "cpa", "--no-pager", "-o", "json"]
    if mode == "recent":
        try:
            result = subprocess.run(args + ["--since", "24 hours ago", "-n", "10000"],
                                    capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            print(json.dumps({"error": "Cannot read CPA journal."}), flush=True)
            return 1
        if result.returncode:
            print(json.dumps({"error": "Cannot read CPA journal."}), flush=True)
            return 1
        dedup = EventDeduplicator()
        events = [event for line in result.stdout.splitlines()
                  if (event := parse(line)) and dedup.accept(event)]
        for event in events[-30:]:
            print(json.dumps(event), flush=True)
        if not events:
            print(json.dumps({"notice": "No Codex routing entries in the recent journal."}), flush=True)
        return 0
    try:
        process = subprocess.Popen(args + ["-f", "-n", "0"], stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True)
    except OSError:
        print(json.dumps({"error": "Cannot read CPA journal."}), flush=True)
        return 1
    dedup = EventDeduplicator()
    try:
        for line in process.stdout:
            event = parse(line)
            if event and dedup.accept(event):
                print(json.dumps(event), flush=True)
        return process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    sys.exit(main())

