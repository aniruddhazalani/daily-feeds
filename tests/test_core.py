"""Run with: python -m unittest discover tests"""
import unittest
from datetime import datetime, timedelta, timezone

from feeds import config
from feeds.filter import canonical_url, cluster_items, filter_items
from feeds.group import group_stories
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

    def test_slow_section_keeps_older_stories_but_others_do_not(self):
        # bis_press feeds both central_banks (normal window) and dedollarization (7 days).
        old = Cluster([item("BIS report on mBridge and cross-border payments in yuan and rupee", source_id="bis_press",
                            kind="official", hours_old=200)])
        older_than_week, _ = score(self.cfg, self.cfg.section("finance.dedollarization"), old, NOW)
        self.assertIsNone(older_than_week)
        four_days = Cluster([item("BIS report on mBridge and cross-border payments in yuan and rupee", source_id="gn_dedollar",
                                  kind="search", hours_old=96)])
        slow, _ = score(self.cfg, self.cfg.section("finance.dedollarization"), four_days, NOW)
        self.assertIsNotNone(slow)
        news = Cluster([item("Fed holds interest rates, signals cuts", source_id="gn_rates", kind="search", hours_old=96)])
        normal, reason = score(self.cfg, self.cfg.section("finance.central_banks"), news, NOW)
        self.assertIsNone(normal)
        self.assertIn("window", reason)

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


class StoryGrouping(unittest.TestCase):
    FILLER = [  # a realistic background so word rarity (IDF) behaves like a real day
        "Fed holds interest rates steady as inflation cools", "Oil prices climb on Middle East supply fears",
        "India beat Zimbabwe to sweep T20 series", "Arsenal edge Everton in late thriller",
        "Tesla begins production of Optimus robot", "Election Commission announces Bihar poll dates",
        "Trump says Ukraine must make a deal with Russia", "Trump signs order on federal hiring freeze",
        "Nvidia launches new open models for agents", "Monsoon withdraws from northwest India",
        "Bank of Japan keeps policy unchanged", "Brent crude settles above $110 a barrel",
    ]

    def grouped(self, titles):
        items = [item(t, url=f"https://site{i}.com/a", outlet=f"Outlet {i}") for i, t in enumerate(titles + self.FILLER)]
        return group_stories([Cluster([it]) for it in items], similarity=0.4)

    def group_of(self, groups, title):
        return next(g for g in groups if any(it.title == title for it in g.items))

    def test_same_story_with_different_headlines_is_grouped(self):
        a = "England manager Sarina Wiegman signs contract extension"
        b = "Sarina Wiegman signs new England contract until 2029"
        groups = self.grouped([a, b])
        self.assertEqual({it.title for it in self.group_of(groups, a).items}, {a, b})

    def test_stories_sharing_only_a_common_name_stay_apart(self):
        a = "Trump says Ukraine must make a deal with Russia"
        b = "Trump signs order on federal hiring freeze"
        groups = self.grouped([])
        self.assertNotIn(b, {it.title for it in self.group_of(groups, a).items})

    def test_articles_days_apart_are_not_grouped(self):
        a = item("Sarina Wiegman signs contract extension with England", url="https://a.com/1", hours_old=1)
        b = item("Sarina Wiegman signs new England contract until 2029", url="https://b.com/2", hours_old=80)
        filler = [item(t, url=f"https://f{i}.com") for i, t in enumerate(self.FILLER)]
        groups = group_stories([Cluster([x]) for x in [a, b, *filler]], similarity=0.4, max_hours_apart=48)
        self.assertEqual(len(self.group_of(groups, a.title).items), 1)


class Impact(unittest.TestCase):
    FAKE = """#!/usr/bin/env python3
import json, re, sys
rs = [{"id": int(m.group(1)), "impact": 1 if "slams" in l else 5, "label": "rhetoric" if "slams" in l else "news",
       "why": "test"} for l in sys.stdin.read().splitlines() for m in [re.match(r"\\[(\\d+)\\]", l)] if m]
print(json.dumps({"type": "result", "is_error": False, "result": "", "structured_output": {"ratings": rs}}))
"""

    def setUp(self):
        import os, tempfile
        from feeds import impact
        self.cfg = config.load(with_discovered=False)
        self.cfg.settings["impact"] = {**self.cfg.settings.get("impact", {}), "batch_size": 2, "parallel": 1}
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path, self.old_cache = os.environ["PATH"], impact.CACHE_PATH
        impact.CACHE_PATH = __import__("pathlib").Path(self.tmp.name) / "ratings.json"

    def tearDown(self):
        import os
        from feeds import impact
        os.environ["PATH"], impact.CACHE_PATH = self.old_path, self.old_cache
        self.tmp.cleanup()

    def fake_cli(self, body):
        import os, stat
        path = os.path.join(self.tmp.name, "claude")
        with open(path, "w") as f:
            f.write(body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        os.environ["PATH"] = self.tmp.name + os.pathsep + self.old_path

    def stories(self):
        a = Scored(cluster=Cluster([item("Cabinet approves new semiconductor mission", url="https://a.com/1")]),
                   section_key="politics.india_governance", score=8, primary=None)
        b = Scored(cluster=Cluster([item("Leader slams rival over remark at rally", url="https://b.com/2")]),
                   section_key="politics.india_politics", score=8, primary=None)
        c = Scored(cluster=Cluster([item("RBI holds repo rate steady at policy meeting", url="https://c.com/3")]),
                   section_key="finance.central_banks", score=8, primary=None)
        for s in (a, b, c):
            s.primary = s.cluster.items[0]
        return [(a, "India › Governance"), (b, "India › Politics"), (c, "Finance › Central banks")]

    def test_ratings_are_parsed_cached_and_reused(self):
        from feeds import impact
        from feeds.rank import story_key
        self.fake_cli(self.FAKE)
        stories = self.stories()
        rated = impact.rate(self.cfg, stories, {}, save=True)
        self.assertEqual(rated[story_key(stories[0][0])]["impact"], 5)
        self.assertEqual(rated[story_key(stories[1][0])]["label"], "rhetoric")
        self.fake_cli("#!/bin/sh\nexit 1\n")  # a broken CLI: cached ratings must still be used
        again = impact.rate(self.cfg, stories, {}, save=False)
        self.assertEqual(len(again), 3)

    def test_failing_cli_leaves_stories_unrated(self):
        from feeds import impact
        self.fake_cli("#!/bin/sh\necho 'OAuth access token is invalid' >&2\nexit 1\n")
        self.assertEqual(impact.rate(self.cfg, self.stories(), {}, save=False), {})


class RatedRanking(unittest.TestCase):
    def test_unrated_filler_dropped_low_impact_collapsed_failed_batches_kept(self):
        from feeds.rank import finalize, story_key
        cfg = config.load(with_discovered=False)
        feed = next(f for f in cfg.feeds if f.id == "ai")
        sec = feed.sections[0]

        def story(title, sc):
            it = item(title, url=f"https://x.com/{abs(hash(title))}")
            return Scored(cluster=Cluster([it]), section_key=sec.key, score=sc, primary=it)

        high, low, filler, failed = (story("Frontier lab releases new model", 9), story("Minor seed round closes", 8),
                                     story("Unrated filler story here", 7), story("Story from a failed batch", 6))
        cands = {s.id: {"news": [], "analysis": [], "papers": []} for s in feed.sections}
        cands[sec.id]["news"] = [high, low, filler, failed]
        ratings = {story_key(high): {"impact": 5, "label": "news", "why": "x"},
                   story_key(low): {"impact": 1, "label": "minor", "why": "y"}}
        out = finalize(cfg, feed, cands, None, ratings, unrated_ok={story_key(failed)})[sec.id]
        self.assertEqual([s.primary.title for s in out["news"]], ["Frontier lab releases new model", "Story from a failed batch"])
        self.assertEqual([s.primary.title for s in out["low"]], ["Minor seed round closes"])


class RulesAndStorylines(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load(with_discovered=False)

    def test_bigger_funding_rounds_score_higher(self):
        from feeds.rank import money_bonus
        self.assertGreater(money_bonus("raises $1.5B Series E"), money_bonus("raises $100 million"))
        self.assertGreater(money_bonus("raises $100 million"), money_bonus("raises $5 million seed"))
        self.assertEqual(money_bonus("no amount here"), 0)

    def test_rhetoric_ranks_below_substance(self):
        sec = self.cfg.section("politics.india_politics")
        rhetoric, _ = score(self.cfg, sec, Cluster([item("Amit Shah slams Congress, takes dig at Rahul Gandhi over remarks",
                                                         source_id="ie_political_pulse")]), NOW)
        substance, _ = score(self.cfg, sec, Cluster([item("Election Commission announces Bihar assembly election dates",
                                                          source_id="ie_political_pulse")]), NOW)
        self.assertGreater(substance.score, rhetoric.score if rhetoric else 0)

    def test_continuing_storyline_is_recognised(self):
        from feeds.group import match_previous
        today = [Cluster([item("Evacuations begin in Oleshky under Russia-Ukraine ceasefire brokered by Melania Trump")])]
        prev = [{"text": "Ceasefire negotiated by Melania Trump holds in Russia-occupied Oleshky", "title": "x",
                 "date": "2026-10-28", "day": 1, "outlets": 3},
                {"text": "Fed holds interest rates steady as inflation cools", "title": "y", "date": "2026-10-28",
                 "day": 1, "outlets": 3}]
        filler = [Cluster([item(t, url=f"https://f{i}.com")]) for i, t in enumerate(StoryGrouping.FILLER)]
        m = match_previous(today + filler, prev, similarity=0.4, min_shared=3)
        self.assertEqual(m.get(id(today[0]))["title"], "x")


if __name__ == "__main__":
    unittest.main()
