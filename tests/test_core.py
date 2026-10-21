"""Run with: python -m unittest discover tests"""
import unittest
from datetime import datetime, timedelta, timezone

from feeds import config
from feeds.filter import canonical_url, cluster_items, filter_items
from feeds.models import Cluster, Item, Scored
from feeds.rank import balance, matches, score

NOW = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)


def item(title, url="https://example.com/a", source_id="bbc_world", kind="news", hours_old=1, outlet="BBC World"):
    return Item(title=title, url=url, outlet=outlet, domain="example.com", source_id=source_id, kind=kind,
                published=NOW - timedelta(hours=hours_old))


class TermMatching(unittest.TestCase):
    def test_short_acronyms_are_case_sensitive(self):
        self.assertTrue(matches("ICE", "ICE raids in Chicago"))
        self.assertFalse(matches("ICE", "Ice hockey final"))
        self.assertFalse(matches("Fed", "fed up with delays"))

    def test_word_boundaries_and_symbols(self):
        self.assertTrue(matches("OPEC+", "OPEC+ agrees to raise output"))
        self.assertTrue(matches("H-1B", "New H-1B fee rule"))
        self.assertFalse(matches("war", "Warsaw summit"))


class Urls(unittest.TestCase):
    def test_canonical_url_strips_tracking_and_amp(self):
        self.assertEqual(canonical_url("http://www.x.com/story/amp/?utm_source=t&id=3"), "https://x.com/story?id=3")


class Clustering(unittest.TestCase):
    def test_same_story_merges_and_different_story_does_not(self):
        a = item("Fed holds interest rates steady and signals two cuts next year", url="https://a.com/1")
        b = item("Fed holds interest rates steady, signals two cuts next year", url="https://b.com/2", outlet="Reuters")
        c = item("ECB raises rates for the first time since 2023 amid inflation", url="https://c.com/3")
        clusters = cluster_items([a, b, c])
        self.assertEqual(sorted(len(cl.items) for cl in clusters), [1, 2])


class Filtering(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load(with_discovered=False)

    def test_seen_yesterday_is_dropped_but_seen_today_is_kept(self):
        it = item("Some headline about world politics today")
        key = "u:" + canonical_url(it.url)
        kept, _ = filter_items(self.cfg, [it], {key: "2026-10-19"}, "2026-10-20", NOW)
        self.assertEqual(kept, [])
        kept, _ = filter_items(self.cfg, [it], {key: "2026-10-20"}, "2026-10-20", NOW)
        self.assertEqual(kept, [it])

    def test_old_news_and_job_posts_are_dropped(self):
        old = item("Ceasefire talks resume in Cairo", hours_old=72)
        job = item("Staff Engineer, Autonomy (R5682) at Shield AI")
        kept, stats = filter_items(self.cfg, [old, job], {}, "2026-10-20", NOW)
        self.assertEqual(kept, [])
        self.assertEqual(stats["window"], 1)
        self.assertEqual(stats["junk"], 1)


class Scoring(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load(with_discovered=False)

    def test_relevant_story_scores_and_excluded_story_drops(self):
        sec = self.cfg.section("finance.oil")
        good, _ = score(self.cfg, sec, Cluster([item("Brent crude jumps as OPEC+ cuts output", source_id="eia", kind="official")]), NOW)
        self.assertIsNotNone(good)
        bad, reason = score(self.cfg, sec, Cluster([item("Olive oil prices hit record as crude costs rise", source_id="eia", kind="official")]), NOW)
        self.assertIsNone(bad)
        self.assertIn("excluded", reason)

    def test_item_from_unlisted_source_is_not_a_candidate(self):
        sec = self.cfg.section("finance.oil")
        s, reason = score(self.cfg, sec, Cluster([item("Brent crude jumps", source_id="cricinfo")]), NOW)
        self.assertIsNone(s)


class Balance(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load(with_discovered=False)

    def scored(self, title, domain, score, extra=()):
        it = item(title, url=f"https://{domain}/{abs(hash(title))}")
        it.domain = domain
        cl = Cluster([it, *extra])
        return Scored(cluster=cl, section_key="politics.world", score=score, primary=it)

    def test_lean_lookup_includes_subdomains(self):
        self.assertEqual(self.cfg.lean("www.theguardian.com"), "left")
        self.assertEqual(self.cfg.lean("moxie.foxnews.com"), "right")
        self.assertEqual(self.cfg.lean("timesofindia.indiatimes.com"), "center")
        self.assertIsNone(self.cfg.lean("example.com"))

    def test_left_cannot_run_ahead_when_right_stories_exist(self):
        ranked = [self.scored("Left story one about the summit", "theguardian.com", 10),
                  self.scored("Left story two about the summit", "aljazeera.com", 9),
                  self.scored("Left story three about the summit", "theguardian.com", 8),
                  self.scored("Right story one about the summit", "foxnews.com", 5)]
        picked = balance(self.cfg, ranked, 3)
        self.assertEqual([self.cfg.lean(s.primary.domain) for s in picked], ["left", "right", "left"])

    def test_same_story_is_shown_from_the_other_side_when_possible(self):
        fox = item("Summit ends without deal on Ukraine", url="https://foxnews.com/x")
        fox.domain = "foxnews.com"
        ranked = [self.scored("Left story one about the summit", "theguardian.com", 10),
                  self.scored("Summit ends without deal on Ukraine", "aljazeera.com", 9, extra=[fox])]
        picked = balance(self.cfg, ranked, 2)
        self.assertEqual(picked[1].primary.domain, "foxnews.com")

    def test_nothing_is_dropped_when_only_one_side_covers_the_news(self):
        ranked = [self.scored(f"Left story number {i} about the vote", "theguardian.com", 10 - i) for i in range(4)]
        self.assertEqual(len(balance(self.cfg, ranked, 4)), 4)


if __name__ == "__main__":
    unittest.main()
