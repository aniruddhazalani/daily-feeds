# Daily Feeds

A personal news page with five feeds: **Politics, Finance, AI, Football, Other Sports**. A GitHub Action rebuilds it every morning (scheduled from 01:07 IST because GitHub starts runs hours late, so it's ready by 6:00) and publishes it to GitHub Pages.

- About 190 trusted sources: outlet RSS, official press releases, expert blogs and newsletters, arXiv, Hugging Face Daily Papers, and Google News searches for topics no single outlet covers well.
- Headlines and links only. No AI summaries and no API keys.
- The app also finds **new sources** on its own. They're added at low weight, marked NEW SOURCE, and listed in the "New sources" tab, so you can promote or mute them.

See [PLAN.md](PLAN.md) for the full design.

## On the page

- **Impact rating:** Claude reads every candidate story in Politics, Finance and AI and rates it 1–5 for you, using the reader profile in `settings.impact.profile`. Stories rated 1–2 are hidden, and the rest are ordered by impact. Each shows its rating and one line on why it matters, plus an **In depth** or **Opinion** label where relevant. It runs through your Claude subscription (see *How it runs*); without it, the page falls back to rule-based ranking.
- **Developing:** a headline that continues a storyline shown in the last 3 days moves to a compact "Developing" list at the bottom of its section, with a "Day N" label, unless its coverage jumped (2× or +5 outlets), which signals a real new development.
- **Top stories:** the first tab lists the 15 most widely covered stories of the day across every feed (3+ outlets). Each is labelled with its feed and section; click the label to jump there. Tune with `settings.top_stories`.
- **Read tracking:** opening any article of a story marks the story as read, and it fades. "Hide read" hides read stories, and "Mark this tab read" clears a tab. Tab counts show unread stories. Stories that weren't on the page the last time you looked get a **New** badge. All of this is stored in your browser only, so each device keeps its own.
- **Refresh:** the button rebuilds the page with the latest news (about 3 minutes) and reloads it when the new version is live. It's limited to **once an hour**. The button shows when the next refresh is allowed, and the workflow itself refuses manual builds within an hour of the last build (`settings.refresh.min_minutes`). One-time setup per device: the first click asks for a GitHub fine-grained token with **Actions: Read and write** on this repository only. It's stored only in that browser and sent only to GitHub. To bypass the limit yourself, run the workflow on GitHub with **force** ticked.

## Run locally

```bash
uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m feeds build            # fetch, rank, discover, write data/ and site/
.venv/bin/python -m http.server 8765 --directory site
```

Other commands:

| Command | What it does |
|---|---|
| `python -m feeds build --no-save` | Dry run: renders `site/` but writes nothing to `data/` |
| `python -m feeds build --no-discover` | Skip source discovery |
| `python -m feeds build --explain finance.oil` | Print every candidate for a section with its score breakdown and why it was kept or dropped |
| `python -m feeds check-sources` | Test every source and suggest a working feed URL for broken ones |
| `python -m feeds check-sources --only eia,opec` | Test only some sources |
| `python -m unittest discover tests` | Run the tests |

## Everyday changes (all in `feeds.yaml`)

**Add a source:** define it under `sources:`, then add its id to one or more sections' `sources:` lists.
```yaml
  my_blog: { type: rss, kind: blog, name: My Blog, url: "https://example.com/feed", topical: true }
```
- `kind` is one of `official | news | blog | paper | search`. It sets the badge, the time window and the default weight.
- `topical: true` means every post is on-topic for its sections (+3 score). Only use it for single-subject sources.
- If a site has no RSS, use `type: gnews` with `query: "site:example.com"`.
- Some publishers block GitHub's servers even though their feeds work from your Mac. Add `fallback: "site:example.com"` and the app will follow that publication through Google News whenever the feed fails. Substack feeds do this automatically.
- Run `python -m feeds check-sources --only my_blog` to confirm it works.

**Add a section or feed:** copy an existing block under `feeds:`. A section needs `title`, `sources` and `include` keywords; `exclude`, `require_any`, `min_score` and `max_items` are optional. Feeds and sections are only ever created here, never by the app.

**Tune a section:** run `--explain feed.section`, then adjust keyword weights, `exclude`, or `min_score`.
- Short capitalised terms (`ICE`, `OPT`, `Fed`) match case-sensitively. Everything else ignores case.
- `junk_titles` under `settings` drops job ads, archive pages and similar everywhere.

**Quality rules:**
- `penalize:` on a section subtracts points for point-scoring words. India and Politics use the shared `rhetoric_penalty` list (slams, jibe, war of words…).
- `money_bonus: true` ranks funding stories by round size.
- On a feed, `vetted_only: true` keeps Google News results only from outlets in `settings.vetted_domains` (or trusted sources), or when such an outlet covers the same story.
- `exclude_titles:` drops low-value formats (tutorials, events, podcasts, listicles, customer stories).
- Stock-tip and SEO sites are muted in `ignore_sources`.

**Slow sections:** a section can set `window_hours` to keep stories longer. De-dollarization, Project 2025 / Agenda 2030, Recommendation systems, Conferences and Champions League use 7 days (`168`). The already-shown list stops repeats, so a longer window only adds stories you haven't seen.

**Story grouping:** articles about the same story are grouped under one entry, even when the headlines differ. Expand "N more articles" to see the others with their outlet and lean. Grouping compares the distinctive words in headlines and snippets, weighted by how rare each word is that day, so names count for more than common words like "Trump" or "India". News, analysis and papers are grouped separately. Tune it with `settings.story_grouping`: raise `similarity` (default 0.4) if unrelated stories end up together, lower it if one story is split across entries.

**Political balance:** `leans:` rates outlet domains as left, center or right (subdomains included). Each headline shows its outlet's lean, and Politics sections show a Left / Center / Right count. Feeds with `balance: true` (Politics) never let left or right get more than one item ahead when the other side has qualifying stories. The app first tries the same story from an outlet on the other side, then the other side's next-best story. Nothing is dropped if only one side covers the news. To change a rating, move the domain between lists.

**Discovered sources** (`data/discovered_sources.yaml`, written by the app):
- **Promote:** copy the line shown in the "New sources" tab into `feeds.yaml` and add it to sections. It's then trusted, and the app drops its own copy.
- **Mute:** add its domain to `ignore_sources:`.
- Discovered sources with nothing relevant for 30 days are retired automatically.

## How it runs

`.github/workflows/daily.yml` has seven scheduled slots, every 30 minutes from 01:07 to 04:07 IST. GitHub starts them about 2–3 hours late on this repo, and news is fetched when a run actually starts. Runs keep building until there's a page built after 03:00 IST; after that, the remaining slots exit in seconds. GitHub's scheduler is best-effort: runs can be an hour or more late, or dropped, so keep several slots and avoid the top of the hour. It also runs on demand via **Actions → Daily feeds → Run workflow**. It:
1. runs the tests,
2. builds the page,
3. commits `data/` (daily snapshots for the archive, the already-shown list, discovery state),
4. deploys `site/` to Pages.

The daily data commit also keeps the repo active, so GitHub doesn't pause the schedule.

One-time setup after pushing: **Settings → Pages → Source: GitHub Actions**.

**Impact rating setup (one time):** the workflow installs Claude Code and runs it headless with your Claude Pro/Max subscription. No API billing; it counts against your plan's usage.
1. On your Mac, run `claude setup-token` and sign in. It prints a long-lived token.
2. Add it as a repository secret: `gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo aniruddhazalani/daily-feeds` (paste when prompted), or use **Settings → Secrets and variables → Actions**.

About 300 stories are rated per build in batches of 40, and ratings are cached for 4 days so refreshes only rate new stories. If the token is missing or expires, the build still runs with rule-based ranking, and the footer stops showing the rating note.
