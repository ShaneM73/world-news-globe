#!/usr/bin/env python3
"""
Collect the world's hottest news stories of the last 24 hours and write them
to data/latest.json (plus a dated copy in data/archive/) for the 3D globe.

Data source: the GDELT Project 2.0 (https://www.gdeltproject.org), free and
key-less. GDELT publishes two files every 15 minutes:

  * <timestamp>.export.CSV.zip   - events, each with a geocoded location
                                   and the URL of the first article reporting it
  * <timestamp>.mentions.CSV.zip - every later article that mentions an event

We read the last N hours of both, group events by their source article,
score each story by how many distinct articles and outlets covered it,
then fetch the real headline / summary / image from the article page.

Only the Python standard library is used, so there is nothing to install.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import io
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GDELT_BASE = os.environ.get("GDELT_BASE", "http://data.gdeltproject.org/gdeltv2/")
USER_AGENT = (
    "Mozilla/5.0 (compatible; WorldNewsGlobe/1.0; "
    "+https://github.com/) Python-urllib"
)
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

csv.field_size_limit(10**7)

# --- GDELT 2.0 event table column indexes ---------------------------------
EV_ID, EV_ACTOR1, EV_ACTOR2 = 0, 6, 16
EV_ROOT_CODE, EV_GOLDSTEIN = 28, 30
EV_MENTIONS, EV_SOURCES, EV_ARTICLES, EV_TONE = 31, 32, 33, 34
EV_GEO_TYPE, EV_GEO_NAME, EV_GEO_COUNTRY = 51, 52, 53
EV_GEO_LAT, EV_GEO_LON = 56, 57
EV_URL = 60

# --- GDELT 2.0 mentions table column indexes ------------------------------
MN_ID, MN_SOURCE, MN_URL = 0, 4, 5

# CAMEO root codes -> broad categories shown in the UI
CATEGORIES = {
    "01": "Diplomacy", "02": "Diplomacy", "03": "Diplomacy", "04": "Diplomacy",
    "05": "Diplomacy", "06": "Cooperation", "07": "Aid", "08": "Cooperation",
    "09": "Investigation", "10": "Demands", "11": "Disapproval",
    "12": "Disapproval", "13": "Threats", "14": "Protest", "15": "Military",
    "16": "Tensions", "17": "Coercion", "18": "Violence", "19": "Conflict",
    "20": "Conflict",
}

# Rank cut-offs for the five impact tiers (tier 5 = biggest story)
TIER_CUTOFFS = [(5, 5), (20, 4), (50, 3), (100, 2)]


def log(*args):
    print(*args, file=sys.stderr, flush=True)


def http_get(url: str, timeout: float = 30, max_bytes: int | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(max_bytes) if max_bytes else resp.read()


def slot_timestamps(hours: int, now: dt.datetime) -> list[str]:
    """GDELT file stamps (every 15 min) covering the last `hours` hours."""
    end = now.replace(second=0, microsecond=0)
    end -= dt.timedelta(minutes=end.minute % 15)
    count = hours * 4
    return [
        (end - dt.timedelta(minutes=15 * i)).strftime("%Y%m%d%H%M%S")
        for i in range(count)
    ]


def latest_stamp() -> dt.datetime | None:
    """Read lastupdate.txt so we never ask for a file that doesn't exist yet."""
    try:
        text = http_get(GDELT_BASE + "lastupdate.txt", timeout=20).decode()
        m = re.search(r"/(\d{14})\.export\.CSV\.zip", text)
        if m:
            return dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    except Exception as exc:  # noqa: BLE001
        log("! could not read lastupdate.txt:", exc)
    return None


def read_zip_rows(data: bytes):
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
            yield from csv.reader(text, delimiter="\t", quoting=csv.QUOTE_NONE)


def download(stamp: str, kind: str) -> bytes | None:
    url = f"{GDELT_BASE}{stamp}.{kind}.CSV.zip"
    for attempt in range(3):
        try:
            return http_get(url, timeout=60)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
        except Exception:  # noqa: BLE001
            pass
    log(f"! gave up on {url}")
    return None


def to_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Step 1: aggregate events + mentions into stories
# ---------------------------------------------------------------------------

def collect_stories(stamps: list[str], workers: int) -> dict[str, dict]:
    stories: dict[str, dict] = {}
    event_to_url: dict[str, str] = {}

    def fetch_pair(stamp):
        return stamp, download(stamp, "export"), download(stamp, "mentions")

    mention_urls: dict[str, set] = defaultdict(set)
    mention_sources: dict[str, set] = defaultdict(set)
    files_ok = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for stamp, export_zip, mentions_zip in pool.map(fetch_pair, stamps):
            if export_zip:
                files_ok += 1
                for row in read_zip_rows(export_zip):
                    if len(row) < 61:
                        continue
                    add_event(stories, event_to_url, row)
            if mentions_zip:
                for row in read_zip_rows(mentions_zip):
                    if len(row) < 6:
                        continue
                    mention_urls[row[MN_ID]].add(row[MN_URL])
                    mention_sources[row[MN_ID]].add(row[MN_SOURCE])

    log(f"  read {files_ok}/{len(stamps)} export files, {len(stories)} candidate stories")

    # Fold mentions (which can arrive hours after the event) into each story
    for event_id, urls in mention_urls.items():
        url = event_to_url.get(event_id)
        if url and url in stories:
            stories[url]["mention_urls"].update(urls)
            stories[url]["mention_sources"].update(mention_sources[event_id])

    for story in stories.values():
        articles = max(len(story["mention_urls"]), story["num_articles"])
        sources = max(len(story["mention_sources"]), story["num_sources"])
        story["articles"] = articles
        story["sources"] = sources
        # Outlet diversity matters more than raw repetition
        story["score"] = round(math.log1p(articles) + 2 * math.log1p(sources), 4)
    return stories


def add_event(stories, event_to_url, row):
    url = row[EV_URL].strip()
    lat, lon = to_float(row[EV_GEO_LAT], None), to_float(row[EV_GEO_LON], None)
    if not url.startswith("http") or lat is None or lon is None:
        return
    if lat == 0 and lon == 0:
        return
    event_id = row[EV_ID]
    event_to_url[event_id] = url
    mentions = to_int(row[EV_MENTIONS])

    story = stories.get(url)
    if story is None:
        story = stories[url] = {
            "url": url,
            "num_articles": 0,
            "num_sources": 0,
            "mention_urls": set(),
            "mention_sources": set(),
            "best_mentions": -1,
            "codes": defaultdict(int),
            "tones": [],
            "goldstein": [],
            "actors": defaultdict(int),
        }
    story["num_articles"] = max(story["num_articles"], to_int(row[EV_ARTICLES]))
    story["num_sources"] = max(story["num_sources"], to_int(row[EV_SOURCES]))
    story["codes"][row[EV_ROOT_CODE]] += 1
    story["tones"].append(to_float(row[EV_TONE]))
    story["goldstein"].append(to_float(row[EV_GOLDSTEIN]))
    for actor in (row[EV_ACTOR1], row[EV_ACTOR2]):
        if actor:
            story["actors"][actor.title()] += 1

    # Prefer the most precise / most-mentioned location for the pin
    geo_type = to_int(row[EV_GEO_TYPE])
    precision = 0 if geo_type in (1,) else 1  # 1 = country centroid
    rank = precision * 10**6 + mentions
    if rank > story["best_mentions"]:
        story["best_mentions"] = rank
        story["lat"], story["lng"] = lat, lon
        story["location"] = row[EV_GEO_NAME]
        story["country"] = row[EV_GEO_COUNTRY]


# ---------------------------------------------------------------------------
# Step 2: pick the top stories, keeping the map geographically diverse
# ---------------------------------------------------------------------------

def pick_candidates(stories: dict, limit: int, per_place: int) -> list[dict]:
    ranked = sorted(stories.values(), key=lambda s: s["score"], reverse=True)
    picked, per_location = [], defaultdict(int)
    for story in ranked:
        place = story.get("location", "")
        if per_location[place] >= per_place:
            continue
        per_location[place] += 1
        picked.append(story)
        if len(picked) >= limit:
            break
    return picked


# ---------------------------------------------------------------------------
# Step 3: fetch real headlines, summaries and images from the articles
# ---------------------------------------------------------------------------

META_RE = re.compile(r"<meta\s[^>]*>", re.I)
ATTR_RE = re.compile(r'([a-zA-Z_:.-]+)\s*=\s*("([^"]*)"|\'([^\']*)\')')
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def parse_meta(page: str) -> dict:
    meta = {}
    for tag in META_RE.findall(page):
        attrs = {m[0].lower(): (m[2] or m[3]) for m in ATTR_RE.findall(tag)}
        key = attrs.get("property") or attrs.get("name")
        if key and "content" in attrs:
            meta.setdefault(key.lower(), html.unescape(attrs["content"]).strip())
    if "title" not in meta:
        m = TITLE_RE.search(page)
        if m:
            meta["title"] = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    return meta


def clean_title(title: str, domain: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    # Strip trailing " | Site Name" / " - Site Name"
    parts = re.split(r"\s+[|\-–—:]\s+", title)
    if len(parts) > 1 and len(parts[-1]) < 40 and len(" ".join(parts[:-1])) > 20:
        title = " - ".join(parts[:-1])
    return title[:220]


def title_from_slug(url: str) -> str:
    path = urllib.parse.urlparse(url).path.rstrip("/")
    slug = path.split("/")[-1] if path else ""
    slug = re.sub(r"\.(html?|php|aspx?)$", "", slug)
    slug = re.sub(r"[-_]+", " ", slug)
    slug = re.sub(r"\b\d{5,}\b", "", slug).strip()
    return slug.capitalize() if len(slug) > 15 else ""


def enrich(story: dict) -> dict:
    url = story["url"]
    domain = urllib.parse.urlparse(url).netloc.removeprefix("www.")
    story["domain"] = domain
    meta = {}
    try:
        raw = http_get(url, timeout=10, max_bytes=400_000)
        meta = parse_meta(raw.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        pass
    title = meta.get("og:title") or meta.get("twitter:title") or meta.get("title") or ""
    story["title"] = clean_title(title, domain) if title else title_from_slug(url)
    story["description"] = (
        meta.get("og:description") or meta.get("description") or ""
    )[:400]
    image = meta.get("og:image") or meta.get("twitter:image") or ""
    if image:
        image = urllib.parse.urljoin(url, image)
    story["image"] = image if image.startswith("https://") else ""
    return story


def normalise(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()[:80]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def finalise(stories: list[dict], max_stories: int) -> list[dict]:
    seen_titles, out = set(), []
    for story in sorted(stories, key=lambda s: s["score"], reverse=True):
        if not story.get("title"):
            continue
        key = normalise(story["title"])
        if key in seen_titles:  # same story syndicated on several sites
            continue
        seen_titles.add(key)
        out.append(story)
        if len(out) >= max_stories:
            break

    result = []
    for rank, story in enumerate(out, start=1):
        tier = 1
        for cutoff, t in TIER_CUTOFFS:
            if rank <= cutoff:
                tier = t
                break
        top_code = max(story["codes"], key=story["codes"].get)
        actors = sorted(story["actors"], key=story["actors"].get, reverse=True)[:3]
        result.append({
            "id": rank,
            "rank": rank,
            "tier": tier,
            "title": story["title"],
            "description": story["description"],
            "url": story["url"],
            "domain": story["domain"],
            "image": story["image"],
            "lat": round(story["lat"], 4),
            "lng": round(story["lng"], 4),
            "location": story.get("location", ""),
            "country": story.get("country", ""),
            "category": CATEGORIES.get(top_code, "General"),
            "actors": actors,
            "articles": story["articles"],
            "sources": story["sources"],
            "score": story["score"],
            "tone": round(sum(story["tones"]) / len(story["tones"]), 2),
        })
    return result


def write_output(stories: list[dict], hours: int, now: dt.datetime, keep_days: int):
    payload = {
        "generated_at": now.replace(microsecond=0).isoformat() + "Z",
        "window_hours": hours,
        "source": "GDELT Project 2.0 (gdeltproject.org)",
        "count": len(stories),
        "stories": stories,
    }
    archive = DATA_DIR / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    day = now.strftime("%Y-%m-%d")
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    (DATA_DIR / "latest.json").write_text(text, encoding="utf-8")
    (archive / f"{day}.json").write_text(text, encoding="utf-8")

    days = sorted((p.stem for p in archive.glob("*.json")), reverse=True)
    for old in days[keep_days:]:
        (archive / f"{old}.json").unlink()
    index = {"latest": day, "days": days[:keep_days]}
    (DATA_DIR / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    log(f"  wrote {len(stories)} stories -> data/latest.json and data/archive/{day}.json")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--hours", type=int, default=24, help="look-back window")
    ap.add_argument("--max-stories", type=int, default=150)
    ap.add_argument("--per-place", type=int, default=4,
                    help="max stories pinned to the same place")
    ap.add_argument("--keep-days", type=int, default=90, help="archive length")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    newest = latest_stamp() or now - dt.timedelta(minutes=20)
    stamps = slot_timestamps(args.hours, newest)
    log(f"> downloading {len(stamps)} GDELT slots ending {stamps[0]}")
    stories = collect_stories(stamps, args.workers)
    if not stories:
        sys.exit("No stories collected - GDELT may be unreachable. Keeping old data.")

    candidates = pick_candidates(stories, args.max_stories * 2, args.per_place)
    log(f"> fetching headlines for {len(candidates)} articles")
    with ThreadPoolExecutor(max_workers=16) as pool:
        enriched = list(pool.map(enrich, candidates))

    final = finalise(enriched, args.max_stories)
    if len(final) < 10:
        sys.exit(f"Only {len(final)} usable stories - keeping old data.")
    write_output(final, args.hours, now, args.keep_days)


if __name__ == "__main__":
    main()
