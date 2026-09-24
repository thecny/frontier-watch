import unittest
from datetime import datetime, timedelta, timezone

from frontier_watch.curate import canonical_url, entry_keys, select_entries
from frontier_watch.models import Entry


NOW = datetime(2026, 9, 24, 1, 0, tzinfo=timezone.utc)


def make_entry(
    id="item-1",
    title="FPGA accelerator",
    url="https://example.org/item/1",
    source="Example",
    published=NOW,
    summary="",
    kind="news",
):
    return Entry(id, title, url, source, published, summary, kind)


class CurateTests(unittest.TestCase):
    def test_selects_dsp_fpga_embedded_and_hardware_topics(self):
        entries = [
            make_entry(id="dsp", title="DSP filter design", url="https://ex.org/dsp"),
            make_entry(id="fpga", title="FPGA fabric", url="https://ex.org/fpga"),
            make_entry(id="embedded", title="嵌入式系统开发", url="https://ex.org/embedded"),
            make_entry(id="hardware", title="Hardware verification", url="https://ex.org/hardware"),
        ]

        result = select_entries(entries, set(), NOW)

        self.assertEqual(
            {item.entry.id: item.topic for item in result},
            {"dsp": "DSP", "fpga": "FPGA", "embedded": "嵌入式", "hardware": "硬件"},
        )

    def test_ignores_items_without_domain_relevance(self):
        result = select_entries(
            [make_entry(title="Football scores", summary="Weekend results")], set(), NOW
        )

        self.assertEqual(result, [])

    def test_includes_lookback_boundary_and_skips_old_future_or_unknown_dates(self):
        entries = [
            make_entry(id="edge", url="https://ex.org/edge", published=NOW - timedelta(hours=72)),
            make_entry(id="old", url="https://ex.org/old", published=NOW - timedelta(hours=72, seconds=1)),
            make_entry(id="future", url="https://ex.org/future", published=NOW + timedelta(seconds=1)),
            make_entry(id="missing", url="https://ex.org/missing", published=None),
            make_entry(id="bad", url="https://ex.org/bad", published="yesterday"),
        ]

        result = select_entries(entries, set(), NOW, lookback_hours=72)

        self.assertEqual([item.entry.id for item in result], ["edge"])

    def test_treats_naive_dates_as_utc(self):
        entry = make_entry(published=(NOW - timedelta(hours=1)).replace(tzinfo=None))

        result = select_entries([entry], set(), NOW)

        self.assertEqual([item.entry.id for item in result], ["item-1"])

    def test_skips_seen_ids_and_canonical_urls(self):
        entries = [
            make_entry(id="seen-id", url="https://ex.org/one"),
            make_entry(id="new-id", url="https://EX.org/two/?utm_source=rss#top"),
            make_entry(id="fresh", url="https://ex.org/three"),
        ]

        result = select_entries(
            entries, {"seen-id", "url:https://ex.org/two"}, NOW
        )

        self.assertEqual([item.entry.id for item in result], ["fresh"])

    def test_deduplicates_batch_by_id_and_url_after_ranking(self):
        entries = [
            make_entry(id="shared", title="FPGA", url="https://ex.org/low"),
            make_entry(id="shared", title="FPGA DSP accelerator", url="https://ex.org/high"),
            make_entry(id="other", title="FPGA", url="https://EX.org/high/?utm_medium=feed"),
        ]

        result = select_entries(entries, set(), NOW)

        self.assertEqual([item.entry.url for item in result], ["https://ex.org/high"])

    def test_ranks_keyword_rich_items_before_newer_weak_matches_and_limits(self):
        entries = [
            make_entry(id="weak", title="DSP board", url="https://ex.org/weak", published=NOW),
            make_entry(
                id="strong",
                title="FPGA DSP accelerator",
                url="https://ex.org/strong",
                published=NOW - timedelta(hours=4),
            ),
            make_entry(id="other", title="DSP chip", url="https://ex.org/other"),
        ]

        result = select_entries(entries, set(), NOW, limit=2)

        self.assertEqual([item.entry.id for item in result], ["strong", "other"])
        self.assertGreater(result[0].score, result[1].score)

    def test_reserves_topic_slots_before_filling_from_global_rank(self):
        entries = [
            make_entry(
                id=f"hardware-{number}",
                title="Hardware ASIC SoC RTL processor",
                url=f"https://ex.org/hardware-{number}",
            )
            for number in range(10)
        ]
        entries.extend(
            [
                make_entry(id="fpga-weak", title="FPGA board", url="https://ex.org/fpga-weak"),
                make_entry(
                    id="fpga-best",
                    title="FPGA field-programmable gate array",
                    url="https://ex.org/fpga-best",
                ),
                make_entry(id="dsp", title="DSP filter", url="https://ex.org/dsp"),
            ]
        )

        result = select_entries(entries, set(), NOW)
        ids = [item.entry.id for item in result]

        self.assertEqual(ids[:2], ["dsp", "fpga-best"])
        self.assertEqual(len(ids), 8)
        self.assertEqual(sum(id.startswith("hardware-") for id in ids), 6)

    def test_bad_text_or_url_fields_are_skipped_safely(self):
        entries = [
            make_entry(id="", title="FPGA", url=""),
            make_entry(id="bad-title", title=None, url="https://ex.org/title"),
            make_entry(id="bad-url", url="not a URL"),
            make_entry(id="valid", url="https://ex.org/valid", summary=None),
        ]

        result = select_entries(entries, set(), NOW)

        self.assertEqual([item.entry.id for item in result], ["valid"])

    def test_entry_keys_match_the_seen_id_contract(self):
        entry = make_entry(id=" paper-42 ", url="HTTPS://Example.ORG/paper/42/?utm_source=feed#abstract")

        self.assertEqual(canonical_url(entry.url), "https://example.org/paper/42")
        self.assertEqual(entry_keys(entry), {"paper-42", "url:https://example.org/paper/42"})

    def test_custom_keywords_replace_default_topic_rules(self):
        entries = [
            make_entry(id="formal", title="Formal verification methods", url="https://ex.org/formal"),
            make_entry(id="fpga", title="FPGA accelerator", url="https://ex.org/fpga"),
        ]

        result = select_entries(
            entries, set(), NOW, keywords={"EDA": ("formal verification",)}
        )

        self.assertEqual([(item.entry.id, item.topic) for item in result], [("formal", "EDA")])

    def test_recognizes_reconfigurable_and_rtl_work_without_explicit_fpga(self):
        entries = [
            make_entry(id="reconfig", title="Reconfigurable accelerator", url="https://ex.org/reconfig"),
            make_entry(id="rtl", title="Verilog RTL synthesis", url="https://ex.org/rtl"),
        ]

        result = select_entries(entries, set(), NOW)

        self.assertEqual(
            {item.entry.id: item.topic for item in result},
            {"reconfig": "可重构计算", "rtl": "硬件"},
        )

    def test_rejects_url_with_malformed_hostname(self):
        entry = make_entry(url="https://exa mple.org/item")

        self.assertEqual(select_entries([entry], set(), NOW), [])


if __name__ == "__main__":
    unittest.main()
