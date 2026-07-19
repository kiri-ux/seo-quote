# adtini · SEO Quote Tool

Internal demo. Partner fills the product form → backend pulls live keyword +
ranking data from DataForSEO → prices on the spring geo-scope ladder → renders a
quote with the full staged breakdown for a human to review before sending.

## What it does (Stages 1, 3, 4 — review is the human at the end)

1. **Keyword list** — crosses seed keywords × geo, expands via DataForSEO keyword
   ideas, drops brand/zero-volume/off-topic terms, buckets into Ultra Competitive
   / Competitive / Long Tail, caps ~20.
2. **Metrics + rank check** — scores the competitive adder from top-of-page bids;
   checks the client domain against the top 100 for each keyword (→ ranking table,
   zero-ranking flag, PAA long-tail pool).
3. **Pricing** — `base = geo anchor + competitive adder + zero-ranking`,
   then the 40% equal-step ladder, plus optional add-on market rate.

All tunable numbers live in the `CFG` block at the top of `app.py`.

## Geo scope → anchor

| Dropdown option        | Anchor  |
|------------------------|---------|
| Single City            | $1,450  |
| Contiguous region      | $2,250  |
| Non-contiguous region  | $2,950  |
| Statewide              | $2,950  |
| Nationwide             | $4,250  |

## Deploy to Render

1. Push this folder to a GitHub repo.
2. Render → New → Web Service → connect the repo (it reads `render.yaml`).
3. Set environment variables in the Render dashboard:
   - `DFS_LOGIN` — your DataForSEO account email
   - `DFS_PASSWORD` — your DataForSEO **API password** (Dashboard → API Access,
   - `ANTHROPIC_API_KEY` — your Anthropic API key (enables the Claude keyword-refinement pass; if omitted, the tool falls back to the rules-based keyword list)
   - `CLAUDE_MODEL` — optional; the model to use (defaults to `claude-sonnet-4-6`)
     not your portal login password)
4. Deploy. Free plan is fine for a demo (cold-starts after idle).

## Run locally

```bash
pip install -r requirements.txt
DFS_LOGIN=you@email DFS_PASSWORD=your_api_password python app.py
# open http://localhost:5000
```

## Notes / open items

- **$3,950 June-floor question is unresolved.** This demo uses the spring ladder
  ($1,450–$4,250 by geo). If Brendan confirms a flat higher floor, edit
  `CFG["geo_anchor"]`.
- **Competitive adder** is bid-only right now; the VersAbility case shows it can
  diverge from a hand-priced quote by ~$200. Calibrate `bid_score_breaks` /
  `competitive_adder` after the blind-rating pass.
- **"Has done SEO in the past"** is captured for the reviewer but does NOT drive
  pricing — only the measured rank check sets the zero-ranking modifier.
- Live API only. Each quote = 1 keyword-ideas call + 1 search-volume call +
  N SERP calls (one per keyword). On the standard/live endpoints that's roughly
  a few cents per quote; the $1 trial credit covers many test runs.
- First live run also verifies DataForSEO's response schema (esp. that
  `high_top_of_page_bid` is populated and PAA nests under `items[].items[].title`).
