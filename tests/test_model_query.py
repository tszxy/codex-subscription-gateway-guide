import contextlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from codex_model_query import EventDeduplicator, main, parse


class QueryTests(unittest.TestCase):
    def fixture(self, timestamp="1760384564000000", message=None):
        return json.dumps({"__REALTIME_TIMESTAMP": timestamp, "MESSAGE": message or
                           "provider=codex model=gpt-6.1-sol account=PRIVATE fixture_body=SECRET"})

    def test_allowlisted_metadata_only(self):
        event = parse(self.fixture())
        self.assertEqual(set(event), {"time", "provider", "model"})
        self.assertEqual(event["model"], "gpt-6.1-sol")
        self.assertNotIn("SECRET", json.dumps(event))
        self.assertNotIn("PRIVATE", json.dumps(event))

    def test_ignore_invalid_and_other_provider(self):
        for line in ("not-json", "[]", "null", self.fixture("bad"),
                     self.fixture(message="provider=claude model=claude-opus-5"),
                     self.fixture(message="provider=codex no_model=true"),
                     self.fixture("9" * 400)):
            with self.subTest(line=line):
                self.assertIsNone(parse(line))

    def test_same_second_same_model_only(self):
        dedup = EventDeduplicator()
        first = {"time": "2026-10-13T19:42:44.123456+00:00", "provider": "codex", "model": "gpt-6.1-sol"}
        self.assertTrue(dedup.accept(first))
        self.assertFalse(dedup.accept({**first, "time": "2026-10-13T19:42:44.999999+00:00"}))
        self.assertTrue(dedup.accept({**first, "model": "gpt-6-luna"}))
        self.assertTrue(dedup.accept({**first, "time": "2026-10-13T19:42:45+00:00"}))

    def test_memory_bound(self):
        dedup = EventDeduplicator(limit=2)
        events = [{"time": f"2026-10-13T19:42:{i:02d}+00:00", "provider": "codex", "model": "fixture"}
                  for i in range(3)]
        for event in events:
            self.assertTrue(dedup.accept(event))
        self.assertEqual(len(dedup.seen), 2)
        self.assertTrue(dedup.accept(events[0]))

    def test_shell_commands_rejected_without_subprocess(self):
        # signal constants are Linux-only on some Python builds: mock signal setup.
        with patch.dict(os.environ, {"SSH_ORIGINAL_COMMAND": "id; cat private"}), \
             patch("codex_model_query.signal.signal"), \
             patch("codex_model_query.signal.SIGHUP", 1, create=True), \
             patch("codex_model_query.subprocess.run") as run, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(), 2)
            run.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())["error"], "Only recent or watch is allowed.")


if __name__ == "__main__":
    unittest.main()
