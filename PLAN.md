# Daily Feeds — Plan

## Goals
- One page with five fixed feeds: **Politics, Finance (macro), AI, Football (soccer), Other Sports**.
- It refreshes once a day, ready by **6:00 AM IST** (Asia/Kolkata).
- **Feeds and sections are fixed by hand** in `feeds.yaml`. The app never creates a feed or section.
- **Sources work in two tiers:**
  - **Trusted:** the curated list in `feeds.yaml` (news outlets, official releases, and blogs for every topic).
  - **Discovered:** the app finds new sources on its own and adds them at lower weight, labelled "new source", so you see when something new appears. You can promote or mute any of them.
- Social media links are allowed. Any site with an RSS feed (Reddit, YouTube channels, Bluesky, Substack) can be a source. X has no free feed, so it isn't supported.
- It shows headlines and links only. No AI summaries and no API keys.

## Architecture
```
GitHub Actions (seven slots 01:07–04:07 IST; GitHub starts them ~2.5h late; builds until one lands after 03:00 IST)
  └─ python -m feeds build
       1. load feeds.yaml + data/discovered_sources.yaml
       2. fetch all sources in parallel (RSS/Atom, arXiv API, Google News RSS queries, HF papers)
       3. normalize → keep only items inside the time window → drop items already shown
       4. dedupe (canonical URL + fuzzy title match), count how many outlets ran each story
       5. score per section: keywords + source weight + recency + outlet count
       6. take the top N per section → render static HTML (Jinja)
       7. discovery: update domain stats, try new candidates, retire dead ones
       8. write site/index.html + site/archive/YYYY-MM-DD.html
  └─ commit data/ back to the repo, deploy site/ to GitHub Pages
```
- Python 3.11 in CI. Dependencies: `feedparser`, `httpx`, `pyyaml`, `jinja2`, `rapidfuzz` (+ `numpy`). Feed links on candidate sites are found with the stdlib HTML parser.
- State lives in `data/` and is committed by the workflow: daily JSON snapshots (about 60 days of archive), `seen.json`, `discovery.json`, and `discovered_sources.yaml`. No server and no database to run.
- If one source fails, the run logs it and carries on. The page footer lists the broken sources.
- Mobile-first page: tabs for each feed, collapsible sections, dark mode.
- A manual "Run workflow" button lets you refresh outside the schedule.
- Note: GitHub Pages on a free plan needs a **public** repo. The page holds only public news links, but the URL is guessable.

## Repo layout
```
feeds.yaml            # feeds, sections, trusted sources, ignore list
feeds/
  config.py           # load and validate feeds.yaml
  fetch.py            # RSS / arXiv / Google News / HF papers fetchers
  filter.py           # time window, seen-filter, dedupe
  rank.py             # keyword + source + recency scoring
  discover.py         # source discovery, RSS autodetect, promote/retire
  render.py           # Jinja → static HTML
  __main__.py         # `python -m feeds build`, `--explain`, `check-sources`
templates/            # page templates + CSS
data/                 # snapshots, seen.json, discovery.json, discovered_sources.yaml
.github/workflows/daily.yml
```

## Feeds and trusted sources
Each section mixes four kinds of source: **official** (press releases, primary data), **news** (outlet RSS), **blogs and newsletters** (expert analysis), and **search** (Google News queries for topics no single outlet covers well).
💲 means paywalled: the headline still shows and is marked with a lock.
RSS URLs are checked in build step 4. A blog with no feed falls back to a Google News `site:` query.

### 1. Politics
**World & geopolitics**
- News: BBC World, Al Jazeera, Guardian World, AP (search), The Diplomat (Asia), Lowy Interpreter
- Blogs and think tanks: War on the Rocks, Foreign Affairs, Foreign Policy 💲, CSIS Analysis, Carnegie Endowment, Brookings (Order from Chaos), Chatham House, ECFR, Lawfare, ISW (conflict updates), ChinaTalk, Phillips O'Brien (Substack), Geopolitical Futures 💲

**US policy affecting immigration**
- Official: USCIS newsroom, State Dept Visa Bulletin, DHS press releases
- Blogs: Migration Policy Institute, American Immigration Council (Immigration Impact), Cato Immigration (Nowrasteh/Bier), Center for Immigration Studies (restrictionist view, kept for balance), Murthy Law NewsFlash (H-1B/GC focus, read by the Indian community), Fragomen Insights, Boundless blog
- Search: H-1B, green card backlog, OPT/STEM OPT, USCIS fee, visa bulletin, travel ban, deportation, immigration executive order

**Indian politics (in depth)**
- News: The Hindu, Indian Express, ThePrint, Scroll, Hindustan Times, NDTV, Mint politics, PIB press releases
- Analysis and newsletters: Carnegie India, ORF (Observer Research Foundation), EPW, The Wire (left-leaning) + Swarajya (right-leaning), kept as a balanced pair

### 2. Finance (macro)
**Central banks & rates**
- Official: Fed, ECB, RBI, BoE, BoJ, BIS press feeds
- Blogs: Liberty Street Economics (NY Fed), St. Louis Fed "On the Economy", Fed Guy (Joseph Wang), ING Think, Mainly Macro (Wren-Lewis), VoxEU/CEPR, PIIE RealTime Economics, Employ America, Apricitas Economics

**Government fiscal & economic policy**
- Official: IMF news, Brookings Hutchins Center, Bruegel
- Search: tariffs, budget, fiscal stimulus, IMF outlook

**Oil — production, OPEC+, war impact (financial angle)**
- Official: EIA (Today in Energy), OPEC press, IEA news
- Blogs: Commodity Context (Rory Johnston), Oxford Institute for Energy Studies, OilPrice.com, Javier Blas (Bloomberg Opinion 💲)
- Search: Brent, OPEC+ output, oil sanctions, Strait of Hormuz, SPR

**De-dollarization & BRICS payment rails**
- Blogs: Brad Setser "Follow the Money" (CFR), Atlantic Council GeoEconomics Center (Dollar Dominance Monitor), Michael Pettis (China Financial Markets), OMFIF
- Search: de-dollarization, BRICS currency, mBridge, CIPS, yuan settlement, central bank gold buying

**US debt & interest costs**
- Official: US Treasury press (refunding, auctions), CBO
- Blogs: CRFB (Committee for a Responsible Federal Budget), Peterson Foundation, Bipartisan Policy Center
- Search: Treasury auction, debt ceiling, interest expense, credit rating

**Project 2025 / UN Agenda 2030**
- Official: UN SDG news, IISD SDG Knowledge Hub
- Search: one query for each

### 3. AI
**Funding & hot startups / VC views & AI revenue**
- News: TechCrunch AI, Crunchbase News, VentureBeat AI, CB Insights research, Newcomer, The Information 💲
- VC blogs: a16z, Sequoia, Bessemer Atlas, Greylock, NFX, Elad Gil, Tomasz Tunguz, YC blog
- Analysis: Stratechery 💲, SemiAnalysis 💲, Benedict Evans, Exponential View, Ben's Bites
- Search: AI startup raises Series, AI ARR/revenue, AI valuation

**LLMs**
- Blogs: Interconnects (Nathan Lambert), Ahead of AI (Sebastian Raschka), Latent Space, Simon Willison, Import AI (Jack Clark), The Batch, Lil'Log (Lilian Weng), Chip Huyen, Epoch AI, Hugging Face blog
- Papers: arXiv cs.CL (filtered), Hugging Face Daily Papers

**Recommendation systems**
- Blogs: Eugene Yan, Netflix Tech Blog, Spotify Research, Pinterest Engineering, Meta Engineering (ML), LinkedIn Engineering, Airbnb Tech, DoorDash Engineering, Instacart Tech, Uber Engineering, NVIDIA Merlin, Shaped.ai
- Papers: arXiv cs.IR

**AI in ads & social media**
- News and blogs: AdExchanger, Digiday, Mobile Dev Memo (Eric Seufert), Platformer, Social Media Today, Google Ads & Commerce blog, Amazon Ads news

**Robotics**
- News and blogs: The Robot Report, IEEE Spectrum Robotics, Robohub
- Papers: arXiv cs.RO (filtered)

**Big lab research**
- OpenAI, Anthropic (news and research), Google DeepMind, Google Research, Meta AI, Microsoft Research, Apple ML Research, NVIDIA Technical Blog, Ai2, Mistral, Qwen, Thinking Machines, BAIR, Stanford HAI/CRFM

**Conferences**
- Blogs: NeurIPS blog, ICML, ICLR blog, CVPR, ACL
- Search and arXiv: mentions of NeurIPS, ICML, ICLR, CVPR, ACL, EMNLP, KDD, RecSys, SIGIR, WWW, MLSys (deadlines, accepted papers, awards)

### 4. Football (soccer)
- News: BBC Sport Football, Guardian Football, ESPN FC, Sky Sports Football, The Athletic 💲
- Analysis blogs: Opta Analyst, Hudl StatsBomb blog, Spielverlagerung, Total Football Analysis, Swiss Ramble (club finances), Off The Pitch (business)
- Sections: top stories, transfers, Champions League / Europe, tactics & analysis

### 5. Other sports (combined)
- Cricket: ESPNcricinfo, Cricbuzz, Wisden, The Cricket Monthly, The Cricverse
- Tennis: ATP / WTA news, Tennis.com
- F1: Formula1.com, The Race, Motorsport.com
- Athletics and Olympics: World Athletics, Olympics.com
- US sports: ESPN (NFL, NBA)
- One combined list, tagged by sport.

## How a feed is built

### Structure: Feed → Section → Sources
A **feed** is a tab, such as Finance. A feed has **sections**, such as "Oil & war impact". Each section names its **sources** and the **keywords** that decide what belongs in it. Sources are defined once and can be used by several sections. Each source is fetched only once per run.

```yaml
# feeds.yaml (excerpt)
sources:
  eia:              { type: rss,   url: "https://www.eia.gov/rss/todayinenergy.xml", kind: official, weight: 3 }
  commodity_context:{ type: rss,   url: "https://commoditycontext.substack.com/feed", kind: blog, weight: 2, topical: true }
  bbc_world:        { type: rss,   url: "https://feeds.bbci.co.uk/news/world/rss.xml", kind: news, weight: 2 }
  gn_oil:           { type: gnews, query: '(OPEC+ OR Brent OR "crude output") (sanctions OR war OR supply)', kind: search, weight: 1 }
  arxiv_recsys:     { type: arxiv, query: 'cat:cs.IR AND (abs:recommend* OR abs:ranking)', kind: paper, weight: 2 }
  anthropic:        { type: gnews, query: 'site:anthropic.com', kind: official, weight: 3 }   # no RSS → site: query

ignore_sources: []        # domains discovery must never add (and items from them are dropped)

feeds:
  finance:
    title: Finance (macro)
    sections:
      oil:
        title: Oil — supply, OPEC+, war impact
        sources: [eia, commodity_context, gn_oil, bbc_world]
        include: { "OPEC": 3, "Brent": 3, "crude": 2, "oil price": 3, "barrel": 2,
                   "sanctions": 1, "Strait of Hormuz": 3, "refinery": 1 }
        exclude: ["olive oil", "essential oil", "cooking oil"]
        min_score: 3
        max_items: 12
```
- `topical: true` marks a source that is entirely about the section's subject (for example, Eugene Yan for recsys). Its posts get +3, so they pass the bar even when the title shares no keywords. General sources such as BBC World only get in when their keywords match.
- `kind` sets the time window and the badge shown on the page (official / news / blog / paper / search / new).

### Source types
| Type | How it's fetched | Used for |
|---|---|---|
| `rss` | The site's own RSS/Atom feed | Outlets, central banks, blogs, Substacks, sports sites, Reddit/YouTube if wanted |
| `gnews` | Google News search feed: `news.google.com/rss/search?q=<query> when:1d&hl=en-IN&gl=IN`. The real outlet is read from the `<source>` tag | Cross-outlet topics (de-dollarization, H-1B, AI funding), and sites with no RSS (`site:` queries) |
| `arxiv` | arXiv API, newest submissions first | LLM, recsys and robotics papers |
| `hf_papers` | Hugging Face Daily Papers JSON | Trending research papers |

### Step by step, per run
1. **Fetch.** Pull every trusted and discovered source, 10 at a time, with a 15-second timeout. Failures are logged and skipped.
2. **Normalize.** Each entry becomes one item: `title, url, outlet, domain, published_at, snippet, source_kind` (the snippet is the description with HTML stripped, cut to about 250 characters).
3. **Drop:**
   - Items older than their time window: 36 h for news and search, 72 h for papers (arXiv publishes in batches and skips weekends), 7 days for blogs and official releases.
   - Items **already shown on an earlier day**. `data/seen.json` remembers 14 days of URLs and titles, so a blog post appears once and doesn't come back every day.
   - Items from domains in `ignore_sources`.
   - Junk titles (`settings.junk_titles`): job ads, archive/listing pages, betting odds, live-commentary pages, titles under 3 words.
4. **Merge duplicates (clustering).** Items count as the same story if their URLs match after cleanup (tracking parameters, AMP and `www` removed) or their titles are ≥ 88 % similar (`rapidfuzz` token-sort ratio; titles under 5 words never fuzzy-merge). The cluster is shown once, under the best-weighted outlet, with "also covered by Reuters, BBC, Mint" underneath.
5. **Score each cluster for each section it could belong to:**
   ```
   keyword  = Σ weight of include terms matched (title match ×2, snippet ×1), capped at 10
   topical  = +3 if the source is marked topical for this section
   source   = source weight (official 3, trusted outlet/blog 2, search 1, discovered 1)
   coverage = 1.5 × ln(number of outlets covering it)
   recency  = −(age in hours / 12)      # for blogs and official: −(age in hours / 48)
   score    = keyword + topical + source + coverage + recency
   ```
   Any `exclude` term means the item is dropped from that section. An item below `min_score` is dropped.
6. **Assign to one section per feed.** If an item qualifies for several sections in the same feed, it goes only to its highest-scoring one, so a feed never shows the same story twice. The same story can appear in two **different** feeds, because the angle differs. For example, an Iran strike can be in Politics › Geopolitics and in Finance › Oil.
7. **Cut and order.** Each section is sorted by score and keeps `max_items` (default 12). The page shows the first 5, with "show more" for the rest. Inside a section, blog posts are shown in their own "Analysis" sub-list so they aren't buried under breaking news.
8. **Tag.** Other Sports items get a sport tag from a keyword map (cricket: IPL, Test, ODI, T20, BCCI…; tennis; F1; NFL; NBA…). The page has tag filter chips.
9. **Discover** (see below).
10. **Save and render.** The day's result goes to `data/YYYY-MM-DD.json` and `seen.json` is updated. Then `index.html` and `archive/YYYY-MM-DD.html` are rendered.

### What one item looks like on the page
```
Fed holds rates at 4.25–4.50%, signals two cuts in 2027           ← headline, links to the article
OFFICIAL · Federal Reserve · 3h ago · also: Reuters, Mint, CNBC   ← badge, outlet, age, other coverage
The FOMC kept the target range unchanged and said inflation…      ← snippet (1–2 lines)
```

### Empty or broken sections
- If nothing qualifies, the section shows "Nothing new in the last 24h". It isn't padded with weak matches.
- The page footer lists sources that failed or returned no items, so a dead feed URL is visible.

### Tuning
`python -m feeds build --explain finance.oil` prints every candidate item with its score breakdown and the reason it was kept or dropped. That makes it easy to adjust keywords, weights and `min_score` in `feeds.yaml`.

## Source discovery
The app finds new **sources** on its own. It never creates new feeds or sections.

### Where candidates come from
1. **Search results.** Every `gnews` item carries its real outlet domain. If a domain not yet in the source list produces items that score above `min_score` in some section, it gets a hit for that section.
2. **Citations in trusted blogs.** Outbound links in posts from trusted blogs are collected. When three or more different trusted sources link to the same unknown domain within 14 days, that domain gets a hit. This is how a new Substack or lab blog that experts start citing gets picked up.
3. **New arXiv and HF paper affiliations are not used.** Paper sources are already broad.

Hits are tracked in `data/discovery.json` as per-domain counts over a rolling 14 days, broken down by section.

### Becoming a discovered source
A domain is checked once it reaches **≥ 10 qualifying search items on ≥ 5 different days (raised from 6 / 3 on 2026-10-25), mostly in one section** (general aggregators spread across sections and don't qualify), **or ≥ 3 trusted citations** (raised from 2 on 2026-10-24) in 14 days. Following a domain with no feed through a `site:` query needs twice the search evidence. Domains that fail are not retried for 30 days. The check:
1. Find its feed: `<link rel="alternate" type="application/rss+xml">` on the homepage, then the usual paths (`/feed`, `/rss`, `/rss.xml`, `/atom.xml`, `/index.xml`, `<sub>.substack.com/feed`).
2. Quality bar: the feed parses, has ≥ 3 posts in the last 60 days, isn't an alias of a source we already have, and at least 2 (and ≥ 15 %) of its recent posts score above `min_score` in a section.
3. If it passes, it's added to `data/discovered_sources.yaml` with `kind: discovered`, `weight: 1`, attached to the section(s) where it scored. If no feed exists, it's added as a `site:` Google News query instead.

Guardrails: at most 5 new sources per day, at most 40 discovered sources active at once, and nothing on `ignore_sources`.

### How you see and control it
- Items from discovered sources carry a **NEW SOURCE** badge.
- A **"New sources this week"** panel on the page lists each discovered source with the section it joined, why it was picked (for example "cited by Interconnects and Latent Space" or "6 matching items via search"), sample headlines, and a ready-to-paste YAML line.
- **Promote:** paste that line into `feeds.yaml`. It becomes trusted with your chosen weight.
- **Mute:** add the domain to `ignore_sources`.
- **Auto-retire:** a discovered source with no qualifying items for 30 days is removed. A promoted source never is.

## Build steps
1. Scaffold the repo, `feeds.yaml` with all trusted sources above, and the config loader with validation.
2. Fetchers (RSS, arXiv, Google News query, HF papers), time windows, seen-filter and dedupe.
3. Ranking and the HTML page (tabs, sections, Analysis sub-lists, badges, archive).
4. `python -m feeds check-sources`: confirm every trusted source's RSS URL works, swap dead ones for working URLs or `site:` queries, then tune keywords with `--explain`.
5. Source discovery: domain stats, feed autodetect, quality bar, "New sources" panel.
6. Create the GitHub repo, add the Actions workflow (commits `data/` and deploys Pages), and do a first scheduled run.
7. README: how to add a feed or section, promote or mute a source, and tune a section.

## Depth, India, AI quality and impact (added 2026-10-31)
- **India** is split into foreign relations & summits (MEA, PMO, Gateway House, MP-IDSA, ORF, Carnegie India), governance & policy (PIB Cabinet decisions, PRS, NITI Aayog, *Explained* and op-ed pages), and party politics & elections (capped at 6). A shared `rhetoric_penalty` ranks point-scoring down.
- **In depth:** Politics' analysis list is "In depth & analysis", fed by long-form sources on both sides: The Atlantic and ProPublica (left); The Economist, Reuters Investigates, FT Big Read and Bloomberg Big Take (center); City Journal, The Free Press and National Review (right).
- **AI quality rules:** stock and SEO sites muted. `vetted_only` keeps search results only from vetted outlets. `exclude_titles` drops tutorials, events, podcasts, listicles and customer stories. Funding is ranked by round size, and arXiv papers without HF upvotes are ranked down.
- **Developing:** today's stories are matched (TF-IDF, ≥ 3 shared distinctive words, similarity ≥ 0.4) against headlines from the previous 3 days. Continuations without a coverage jump move to a compact list with "Day N".
- **Impact rating (`feeds/impact.py`):** the top rule-ranked candidates per section (news 20, analysis 10, papers 10) in Politics, Finance and AI are sent in batches of 40 to `claude -p` (Claude Code headless, no tools, JSON-schema output, model `opus`, effort `low`). Each story gets impact 1–5, a label and a one-line why. Ratings are cached 4 days in `data/ratings.json`. Stories below 3 are hidden; the rest are ordered by score + 3 × (impact − 3). Auth is the user's Claude subscription via `CLAUDE_CODE_OAUTH_TOKEN`. If the first batch fails, the remaining batches are skipped and rules alone decide.

## Reading features (added 2026-10-27)
- **Top stories tab:** stories shown in any feed's headlines, ranked by number of outlets and then score. Top 15 with ≥ 3 outlets; each placed at its best-scoring feed and section.
- **Slow sections:** a per-section `window_hours` (7 days for five sections). A source keeps items for the longest window of any section that lists it, but each section only scores items inside its own window. The recency penalty stretches to match.
- **Read tracking (browser-only):** a story is read once any of its articles is opened. Read stories fade or can be hidden, tab counts show unread, and stories not on the page at the last visit get a "New" badge.
- **Refresh button:** calls GitHub's `workflow_dispatch` API with a fine-grained token stored only in that browser, then polls the page and reloads when the new build is live. The hourly limit is enforced in the workflow's `check` job: manual runs within `refresh.min_minutes` of the last build are skipped unless started with `force`.

## Story grouping (added 2026-10-24)
- After near-duplicate merging, `feeds/group.py` groups articles about the same story using TF-IDF over headline (×2) + snippet. Weights come from the day's own items, so rare words (names, places, specific terms) dominate.
- An article joins a group when it shares ≥ 2 distinctive words with it (words in ≤ 3 % of the day's items) and its cosine similarity to the group's centroid is ≥ 0.4, within 48 h. Matching against the centroid instead of pair-to-pair stops chaining into topic blobs. A second pass merges groups that ended up as two halves of one story.
- News, blog analysis and papers are grouped separately. Each entry shows the lead article plus an expandable list of the others (outlet, lean, time). Exclude/require rules look only at the section's own articles.
- Measured on 2026-10-24: ~95 % of sampled groups were the same story. Articles on the page went from 345 to 608 with the same number of slots.

## Political balance (added 2026-10-21)
- Added right / center-right outlets: Fox News, WSJ, Telegraph, Spectator, National Review, The Dispatch, The Free Press, UnHerd, The National Interest, FDD, Hudson, Heritage, AEI, Hoover, NY Post, Washington Examiner, WION. Center: The Hill, Axios. India: Times of India, India Today, News18, Firstpost, Republic, OpIndia, The Pioneer.
- `leans:` in `feeds.yaml` rates outlet domains left / center / right (AllSides / Ad Fontes where available).
- The Politics feed has `balance: true`. When picking each section's headlines and analysis, left and right may never differ by more than one while the other side has a qualifying story. The app prefers the same story from an outlet on the other side, then that side's best other story. Center and unrated outlets don't count.
- Every headline shows its outlet's lean, and Politics sections show Left / Center / Right counts.

## Build notes (what changed during implementation)
- **Sources checked on 2026-10-20:** all 193 return items. Sites that block bots or return HTML (ECFR, IMF, Brookings, AdExchanger, OIES, Mainly Macro, Total Football Analysis) use `site:` searches instead. Dropped because they are inactive or not indexed: Indialogue (no posts since 2021), IISD SDG hub, Chip Huyen (no posts in ~2 years), The Cricket Monthly, Shaped, Immigration Impact, Mobile Dev Memo. India Inside Out and Anticipating the Unintended were removed later: Substack blocks GitHub's servers and Google News doesn't index them.
- Feeds are fetched with a browser user agent, falling back to a feed-reader user agent (ESPN only serves the latter).
- HF Daily Papers is queried for yesterday's date, and upvotes add `ln(1 + upvotes)` to a paper's score.
- Each section shows up to three lists: **Headlines**, **Analysis & blogs**, **Papers**, each capped separately (`max_items`, `max_analysis`, `max_papers`), so papers never crowd out news.
