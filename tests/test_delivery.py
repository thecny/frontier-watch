"""Contract tests for digest formatting and outbound push adapters."""

import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs

from frontier_watch.delivery import DeliveryError, format_digest, send_digest


class FakeResponse:
    def __init__(self, body, status=200):
        self.status = status
        self.body = body

    def read(self):
        return json.dumps(self.body).encode("utf-8")


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def post_succeeding_with(self, body, status=200):
        def post(url, data, headers):
            self.calls.append((url, data, headers))
            return FakeResponse(body, status)

        return post

    def test_digest_contains_date_source_topic_summary_and_original_link(self):
        entry = SimpleNamespace(
            id="paper-1",
            title="A new FPGA signal processor",
            url="https://example.org/paper/1",
            source="arXiv",
            published=datetime(2026, 9, 24, tzinfo=timezone.utc),
            summary=" Low power   DSP accelerator. ",
            kind="paper",
        )
        curated = SimpleNamespace(entry=entry, topic="FPGA / DSP", score=8)

        result = format_digest(
            [curated], datetime(2026, 9, 24, 9, tzinfo=timezone(timedelta(hours=8)))
        )

        for expected in (
            "2026-09-24",
            "A new FPGA signal processor",
            "arXiv",
            "FPGA / DSP",
            "Low power DSP accelerator.",
            "https://example.org/paper/1",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, result)

    def test_serverchan_uses_form_body_and_accepts_business_code_zero(self):
        send_digest(
            "Today's DSP digest",
            "serverchan",
            {"SERVERCHAN_SENDKEY": "SCT_secret"},
            self.post_succeeding_with({"code": 0, "message": "success"}),
        )

        url, data, headers = self.calls[0]
        self.assertEqual(url, "https://sctapi.ftqq.com/SCT_secret.send")
        self.assertEqual(parse_qs(data.decode()), {"title": ["芯片前沿雷达"], "desp": ["Today's DSP digest"]})
        self.assertEqual(headers["Content-Type"], "application/x-www-form-urlencoded; charset=utf-8")

    def test_missing_credentials_prevent_any_request(self):
        for channel in ("serverchan", "bark", "telegram", "wecom"):
            with self.subTest(channel=channel):
                with self.assertRaises(DeliveryError):
                    send_digest("digest", channel, {}, self.post_succeeding_with({"code": 0}))
        self.assertEqual(self.calls, [])

    def test_serverchan_http_success_with_business_error_fails_without_leaking_key(self):
        secret = "SCT_private_value"
        with self.assertRaises(DeliveryError) as raised:
            send_digest(
                "digest",
                "serverchan",
                {"SERVERCHAN_SENDKEY": secret},
                self.post_succeeding_with({"code": 40001, "message": secret}),
            )
        self.assertNotIn(secret, str(raised.exception))

    def test_bark_uses_custom_server_and_device_key_in_json(self):
        send_digest(
            "digest body",
            "bark",
            {"BARK_DEVICE_KEY": "device-key", "BARK_SERVER_URL": "https://push.example.org/"},
            self.post_succeeding_with({"code": 200, "message": "success"}),
        )

        url, data, headers = self.calls[0]
        self.assertEqual(url, "https://push.example.org/push")
        self.assertEqual(json.loads(data), {
            "device_key": "device-key",
            "title": "芯片前沿雷达",
            "body": "digest body",
            "group": "frontier-watch",
        })
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")

    def test_bark_http_success_with_business_error_fails(self):
        with self.assertRaises(DeliveryError):
            send_digest(
                "digest", "bark", {"BARK_DEVICE_KEY": "key"},
                self.post_succeeding_with({"code": 500, "message": "APNs failed"}),
            )

    def test_empty_bark_server_url_uses_public_default(self):
        send_digest(
            "digest", "bark",
            {"BARK_DEVICE_KEY": "key", "BARK_SERVER_URL": ""},
            self.post_succeeding_with({"code": 200}),
        )
        self.assertEqual(self.calls[0][0], "https://api.day.app/push")

    def test_telegram_sends_chat_message_and_checks_ok_field(self):
        send_digest(
            "digest body", "telegram",
            {"TELEGRAM_BOT_TOKEN": "telegram-secret", "TELEGRAM_CHAT_ID": "12345"},
            self.post_succeeding_with({"ok": True, "result": {"message_id": 1}}),
        )

        url, data, _ = self.calls[0]
        self.assertEqual(url, "https://api.telegram.org/bottelegram-secret/sendMessage")
        self.assertEqual(json.loads(data), {"chat_id": "12345", "text": "digest body"})

        with self.assertRaises(DeliveryError):
            send_digest(
                "digest body", "telegram",
                {"TELEGRAM_BOT_TOKEN": "telegram-secret", "TELEGRAM_CHAT_ID": "12345"},
                self.post_succeeding_with({"ok": False, "description": "Bad Request"}),
            )

    def test_wecom_sends_markdown_and_checks_errcode(self):
        send_digest(
            "digest body", "wecom",
            {"WECOM_WEBHOOK_URL": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=private"},
            self.post_succeeding_with({"errcode": 0, "errmsg": "ok"}),
        )

        url, data, _ = self.calls[0]
        self.assertEqual(url, "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=private")
        self.assertEqual(json.loads(data), {"msgtype": "markdown", "markdown": {"content": "digest body"}})

        with self.assertRaises(DeliveryError):
            send_digest(
                "digest body", "wecom",
                {"WECOM_WEBHOOK_URL": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=private"},
                self.post_succeeding_with({"errcode": 45009, "errmsg": "rate limited"}),
            )

    def test_transport_failure_does_not_echo_credential(self):
        secret = "SCT_private_value"

        def failing_post(url, data, headers):
            raise OSError(f"network failed for {url}")

        with self.assertRaises(DeliveryError) as raised:
            send_digest("digest", "serverchan", {"SERVERCHAN_SENDKEY": secret}, failing_post)
        self.assertNotIn(secret, str(raised.exception))

    def test_telegram_splits_long_message_without_losing_text(self):
        digest = "芯片前沿雷达\n\n" + ("FPGA update and source link\n" * 250)
        self.assertGreater(len(digest), 4096)
        send_digest(
            digest, "telegram",
            {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "12345"},
            self.post_succeeding_with({"ok": True}),
        )
        chunks = [json.loads(data)["text"] for _, data, _ in self.calls]
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(chunk) <= 4096 for chunk in chunks))
        self.assertEqual("".join(chunks), digest)

    def test_unknown_channel_error_does_not_echo_accidentally_pasted_secret(self):
        secret = "SCT_accidentally_pasted_secret"
        with self.assertRaises(DeliveryError) as raised:
            send_digest("digest", secret, {}, self.post_succeeding_with({"ok": True}))
        self.assertNotIn(secret.lower(), str(raised.exception).lower())

    def test_unknown_channel_fails_before_post(self):
        with self.assertRaises(DeliveryError):
            send_digest("digest", "unknown", {}, self.post_succeeding_with({"ok": True}))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
