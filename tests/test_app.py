import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from frontier_watch.app import SourceError, load_keywords, load_state, run
from frontier_watch.models import Entry


NOW = datetime(2026, 9, 24, 1, 0, tzinfo=timezone.utc)


def fpga_entry():
    return Entry(
        id="paper-42",
        title="New FPGA architecture for signal processing",
        url="https://example.org/paper/42?utm_source=feed",
        source="arXiv",
        published=NOW - timedelta(hours=5),
        summary="A reconfigurable DSP accelerator with lower power.",
        kind="paper",
    )


class AppTests(unittest.TestCase):
    def test_dry_run_prints_digest_without_sending_or_saving(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "sent.json"
            result = run(
                now=NOW,
                dry_run=True,
                state_path=state_path,
                fetcher=lambda now, github_token: ([fpga_entry()], []),
                sender=lambda text, channel, env: self.fail("dry run sent a push"),
                env={},
            )
            self.assertEqual(result.status, "preview")
            self.assertIn("New FPGA architecture", result.digest)
            self.assertFalse(state_path.exists())

    def test_failed_delivery_does_not_record_sent_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "sent.json"

            def fail_send(text, channel, env):
                raise RuntimeError("delivery failed")

            with self.assertRaisesRegex(RuntimeError, "delivery failed"):
                run(
                    now=NOW,
                    dry_run=False,
                    state_path=state_path,
                    fetcher=lambda now, github_token: ([fpga_entry()], []),
                    sender=fail_send,
                    env={},
                )
            self.assertFalse(state_path.exists())

    def test_success_is_recorded_and_not_resent(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "sent.json"
            sent = []

            def sender(text, channel, env):
                sent.append(text)

            kwargs = dict(
                now=NOW,
                dry_run=False,
                state_path=state_path,
                fetcher=lambda now, github_token: ([fpga_entry()], []),
                sender=sender,
                env={},
            )
            first = run(**kwargs)
            second = run(**kwargs)
            self.assertEqual((first.status, second.status), ("sent", "empty"))
            self.assertEqual(len(sent), 1)
            self.assertIn("paper-42", load_state(state_path))
            self.assertIn("sent_ids", json.loads(state_path.read_text(encoding="utf-8")))

    def test_all_sources_failed_blocks_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SourceError):
                run(
                    now=NOW,
                    dry_run=False,
                    state_path=Path(directory) / "sent.json",
                    fetcher=lambda now, github_token: ([], ["arxiv unavailable"]),
                    sender=lambda text, channel, env: self.fail("sent without sources"),
                    env={},
                )

    def test_bad_state_data_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "sent.json"
            state_path.write_text('{"sent_ids":"wrong type"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_state(state_path)

    def test_custom_keywords_replace_default_topic_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = Entry(
                id="optical-1",
                title="Photonic accelerator for optical links",
                url="https://example.org/optical-1",
                source="arXiv",
                published=NOW - timedelta(hours=2),
                summary="A new architecture.",
                kind="paper",
            )
            result = run(
                now=NOW,
                dry_run=True,
                state_path=Path(directory) / "sent.json",
                fetcher=lambda now, github_token: ([entry], []),
                env={},
                keywords={"光计算": ["photonic"]},
            )
            self.assertEqual(result.status, "preview")
            self.assertIn("主题：光计算", result.digest)

    def test_load_keywords_rejects_invalid_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "topics.json"
            path.write_text('{"FPGA": []}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_keywords(path)


if __name__ == "__main__":
    unittest.main()
