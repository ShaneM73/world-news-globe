# 🌍 World News Globe

### 👉 [**Open the live globe → shanem73.github.io/world-news-globe**](https://shanem73.github.io/world-news-globe/)

**Designed by [ShaneM73](https://github.com/ShaneM73)**

---

Every day this repo automatically collects the world's biggest news stories of the last 24 hours and pins them on an interactive 3D globe.

- **Bigger story → taller, brighter, faster-flashing marker.** Each story gets one of five impact levels (Major, High, Notable, Moderate, Minor), each with its own color, bar height and pulse ring.
- **Click any marker** (or any item in the list) to fly to it and open the headline, summary, image and a link to the full article.
- **Filter** by keyword or place, show or hide impact levels, and browse past days from the archive.
- **Free to run:** GitHub Actions fetches the news once a day, and GitHub Pages hosts the site. You don't need a server or API key.

## How it works

```
GitHub Actions (daily, 06:17 UTC)
   └─ scripts/fetch_news.py
        1. downloads the last 24 h of GDELT 2.0 event + mention files (every 15 min)
        2. groups events by source article, scores each story by how many
           distinct articles and outlets covered it
        3. keeps the top ~150 (max 4 per place, so one city can't fill the map)
        4. fetches each article's real headline, summary and image
        5. writes data/latest.json  +  data/archive/YYYY-MM-DD.json
   └─ deploys index.html + app.js + style.css + data/ to GitHub Pages
```

**Impact score** = `ln(1 + articles) + 2 × ln(1 + outlets)`. Coverage by many different outlets counts for more than one outlet repeating itself. The levels are set by rank: the top 5 stories are **Major**, ranks 6–20 are **High**, 21–50 are **Notable**, 51–100 are **Moderate**, and the rest are **Minor**. You can change the cut-offs in `TIER_CUTOFFS` in `scripts/fetch_news.py`.

**Visual effects** (in `app.js`, `TIERS`):

| Level | Color | Effect |
|---|---|---|
| Major | red | tallest bar, fast shock-wave rings, flashing glowing beacon |
| High | orange | tall bar, rings, flashing beacon |
| Notable | yellow | medium bar, slower rings |
| Moderate | green | short bar, gentle rings |
| Minor | blue | small dot |

## Setup (about 5 minutes)

1. **Create a new repo** on GitHub (for example `world-news-globe`), public, with no README.
2. **Upload these files.** Unzip, then in the folder run:
   ```bash
   git init -b main
   git add .
   git commit -m "World News Globe"
   git remote add origin https://github.com/<your-username>/world-news-globe.git
   git push -u origin main
   ```
   (Or use **Add file → Upload files** on the GitHub website. Make sure the hidden `.github` folder is included.)
3. **Turn on Pages:** go to repo **Settings → Pages → Build and deployment → Source** and choose **GitHub Actions**.
4. **Allow the workflow to commit:** go to **Settings → Actions → General → Workflow permissions** and choose **Read and write permissions**.
5. **Run it once now:** go to the **Actions** tab → *Update news & deploy globe* → **Run workflow**.
   After about 3–5 minutes your globe is live at `https://<your-username>.github.io/world-news-globe/`.

From then on it updates itself every day. Until the first run finishes, the page shows clearly labelled **sample data**.

## Run locally

```bash
python3 scripts/fetch_news.py          # optional: fetch real data (needs internet, ~2–4 min)
python3 -m http.server 8000            # then open http://localhost:8000
```

Options: `--hours 24`, `--max-stories 150`, `--per-place 4`, `--keep-days 90`.

## Customising

- **Update frequency:** edit the `cron` line in `.github/workflows/update-news.yml` (for example `"0 */6 * * *"` for every 6 hours).
- **Globe look:** in `app.js`, swap `earth-night.jpg` for `earth-blue-marble.jpg`, `earth-day.jpg` or `earth-dark.jpg`.
- **Colors and effects:** edit the `TIERS` table at the top of `app.js`.

## Notes

- Locations come from GDELT's automatic geocoding, so a few pins may be slightly off, or may sit on a country's center point when the article doesn't name a city.
- Some news sites block automated requests. When that happens the headline falls back to the article URL, and stories without any title are dropped.
- Data © [The GDELT Project](https://www.gdeltproject.org), free for open use with attribution. The globe is built with [Globe.gl](https://globe.gl) / [Three.js](https://threejs.org).
