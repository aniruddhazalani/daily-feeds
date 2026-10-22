# Daily Feeds

A personal news page with five feeds: **Politics, Finance, AI, Football, Other Sports**. A GitHub Action rebuilds it every morning (between 03:37 and 05:37 IST, so it's ready by 6:00 even when GitHub runs it late) and publishes it to GitHub Pages.

- About 190 trusted sources: outlet RSS, official press releases, expert blogs and newsletters, arXiv, Hugging Face Daily Papers, and Google News searches for topics no single outlet covers well.
- Headlines and links only. No AI summaries and no API keys.
- The app also finds **new sources** on its own. They're added at low weight, marked NEW SOURCE, and listed in the "New sources" tab, so you can promote or mute them.

See [PLAN.md](PLAN.md) for the full design.

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

**Political balance:** `leans:` rates outlet domains as left, center or right (subdomains included). Each headline shows its outlet's lean, and Politics sections show a Left / Center / Right count. Feeds with `balance: true` (Politics) never let left or right get more than one item ahead when the other side has qualifying stories. The app first tries the same story from an outlet on the other side, then the other side's next-best story. Nothing is dropped if only one side covers the news. To change a rating, move the domain between lists.

**Discovered sources** (`data/discovered_sources.yaml`, written by the app):
- **Promote:** copy the line shown in the "New sources" tab into `feeds.yaml` and add it to sections. It's then trusted, and the app drops its own copy.
- **Mute:** add its domain to `ignore_sources:`.
- Discovered sources with nothing relevant for 30 days are retired automatically.

## How it runs

`.github/workflows/daily.yml` has five scheduled slots: 03:37, 04:07, 04:37, 05:07 and 05:37 IST. The first one that fires builds the page, and the others exit in seconds once this morning's page exists. GitHub's scheduler is best-effort: runs can be an hour or more late, or dropped, so keep several slots and avoid the top of the hour. It also runs on demand via **Actions → Daily feeds → Run workflow**. It:
1. runs the tests,
2. builds the page,
3. commits `data/` (daily snapshots for the archive, the already-shown list, discovery state),
4. deploys `site/` to Pages.

The daily data commit also keeps the repo active, so GitHub doesn't pause the schedule.

One-time setup after pushing: **Settings → Pages → Source: GitHub Actions**.
