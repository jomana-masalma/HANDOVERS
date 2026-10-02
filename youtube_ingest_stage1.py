"""
Stage 1 ingestion script.
Run only when you intentionally want live YouTube API calls (needs YOUTUBE_API_KEY).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import re
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

# --- Curated inputs (PDF) ---
# Fixed list:known video IDs, call videos.list directly (low quota).
VIDEO_URLS: List[str] = [
    "https://www.youtube.com/watch?v=dItUGF8GdTw",
    "https://www.youtube.com/watch?v=qMrnVkDH2Ak",
    "https://www.youtube.com/watch?v=vNDYUlxNIAA",
    "https://www.youtube.com/watch?v=Bry8J78Awq0",
    "https://www.youtube.com/watch?v=NHjgKe7JMNE",
    "https://www.youtube.com/watch?v=Cum3k-Wglfw",
    "https://www.youtube.com/watch?v=pvWzQ1MmSns",
    "https://www.youtube.com/watch?v=3lPnN8omdPA",
    "https://www.youtube.com/watch?v=m8WomdCLBqE",
    "https://www.youtube.com/watch?v=ZkXrTHpnQrQ",
]

CHANNEL_HANDLES: List[str] = [
    "@TEDEd",
    "@CasuallyExplained",
    "@TEDx",
    "@bbcideas",
    "@WirelessPhilosophy",
]

VIDEO_PARTS = ",".join(
    [
        "snippet",
        "contentDetails",
        "statistics",
        "status",
        "topicDetails",
        "recordingDetails",
        "liveStreamingDetails",
        "localizations",
        "player",
    ]
)

CHANNEL_PARTS = ",".join(
    [
        "snippet",
        "contentDetails",
        "statistics",
        "status",
        "topicDetails",
        "brandingSettings",
        "localizations",
    ]
)

SEARCH_PARTS = "snippet"

_VIDEO_ID_RE = re.compile(r"(?:v=)([A-Za-z0-9_-]{11})")


@dataclass
class IngestConfig:
    """Runtime configuration; overridable via CLI."""

    output_dir: Path = field(default_factory=lambda: Path("."))
    api_key_env: str = "YOUTUBE_API_KEY"
    search_query: str = "critical thinking"
    search_max_pages: int = 2
    search_page_size: int = 25
    request_delay_s: float = 0.05
    user_agent: str = "stage1-youtube-ingest/1.0 (research; YouTube Data API v3)"
def setup_logging(verbose: bool) -> None:
    # -v gives DEBUG (API params, pagination); default INFO shows progress only.
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def extract_video_id(url: str) -> str:
    m = _VIDEO_ID_RE.search(url)
    if not m:
        raise ValueError(f"Could not extract video id from: {url}")
    return m.group(1)


@dataclass(frozen=True)
class YouTubeApiClient:
    # Thin HTTP wrapper: one place for auth, errors, and no much delay between calls.
    api_key: str
    session: requests.Session
    request_delay_s: float

    def get(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        #  request behavior:
        # - add the API key consistently
        # - fail fast with readable error payloads
        # - optional tiny delay , don't spam the API during pagination
        url = f"{YOUTUBE_API_BASE}/{resource.lstrip('/')}"
        q = dict(params)
        q["key"] = self.api_key
        logging.debug("GET %s params=%s", resource, {k: v for k, v in q.items() if k != "key"})
        r = self.session.get(url, params=q, timeout=60)
        if r.status_code != 200:
            try:
                payload = r.json()
            except Exception:
                payload = {"text": r.text}
            raise RuntimeError(
                f"HTTP {r.status_code} for {resource}: "
                f"{json.dumps(payload, ensure_ascii=False)[:2000]}"
            )
        if self.request_delay_s > 0:
            time.sleep(self.request_delay_s)
        return r.json()


def chunked(seq: Sequence[str], n: int) -> Iterable[List[str]]:
    # YouTube allows up to 50 IDs per videos.list / channels.list request.
    for i in range(0, len(seq), n):
        yield list(seq[i : i + n])


def videos_list(client: YouTubeApiClient, video_ids: Sequence[str]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for batch in chunked(list(video_ids), 50):
        #  The API accepts up to 50 IDs per request; to save quota.
        data = client.get(
            "videos",
            {"part": VIDEO_PARTS, "id": ",".join(batch), "maxResults": 50},
        )
        items.extend(data.get("items", []))
    return items


def channels_list(client: YouTubeApiClient, channel_ids: Sequence[str]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for batch in chunked(list(channel_ids), 50):
        # Same batching logic as videos_list (max 50 IDs per request).
        data = client.get(
            "channels",
            {"part": CHANNEL_PARTS, "id": ",".join(batch), "maxResults": 50},
        )
        items.extend(data.get("items", []))
    return items


def resolve_channel_ids_via_search(
    client: YouTubeApiClient, handles: Sequence[str]
) -> Tuple[List[str], List[Tuple[str, str]]]:
    # Handles (@TEDEd) are not channel IDs — search.list(type=channel) resolves them first.
    channel_ids: List[str] = []
    failures: List[Tuple[str, str]] = []

    for h in handles:
        q = h.lstrip("@").strip()
        if not q:
            failures.append((h, "empty handle"))
            continue

        data = client.get(
            "search",
            {
                "part": SEARCH_PARTS,
                "q": q,
                "type": "channel",
                "maxResults": 5,
            },
        )
        found = data.get("items", [])
        if not found:
            failures.append((h, f"no search results for q={q!r}"))
            continue

        cid = (found[0].get("id") or {}).get("channelId")
        if not cid:
            failures.append((h, "search result missing channelId"))
            continue
        channel_ids.append(cid)

    seen: set[str] = set()
    unique: List[str] = []
    for cid in channel_ids:
        if cid in seen:
            continue
        seen.add(cid)
        unique.append(cid)
    return unique, failures


def search_videos(
    client: YouTubeApiClient,
    query: str,
    max_pages: int,
    page_size: int,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    for _ in range(max_pages):
        # search.list is higher quota cost than list endpoints, so:
        # - a small controlled page_size
        # - a small max_pages (feasibility sample, not full crawl)
        params: Dict[str, Any] = {
            "part": SEARCH_PARTS,
            "q": query,
            "maxResults": page_size,
            "type": "video",
            "order": "relevance",
            "safeSearch": "none",
        }
        if page_token:
            params["pageToken"] = page_token
        data = client.get("search", params)
        items.extend(data.get("items", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return items


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv_flat(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def flatten_video_item(item: Dict[str, Any]) -> Dict[str, Any]:
    sn = item.get("snippet") or {}
    st = item.get("statistics") or {}
    cd = item.get("contentDetails") or {}
    return {
        "videoId": item.get("id"),
        "channelId": sn.get("channelId"),
        "channelTitle": sn.get("channelTitle"),
        "title": sn.get("title"),
        "publishedAt": sn.get("publishedAt"),
        "duration": cd.get("duration"),
        "viewCount": st.get("viewCount"),
        "likeCount": st.get("likeCount"),
        "commentCount": st.get("commentCount"),
    }


def flatten_channel_item(item: Dict[str, Any]) -> Dict[str, Any]:
    sn = item.get("snippet") or {}
    st = item.get("statistics") or {}
    return {
        "channelId": item.get("id"),
        "title": sn.get("title"),
        "customUrl": sn.get("customUrl"),
        "publishedAt": sn.get("publishedAt"),
        "country": sn.get("country"),
        "subscriberCount": st.get("subscriberCount"),
        "viewCount": st.get("viewCount"),
        "videoCount": st.get("videoCount"),
    }


def channel_context_by_id(channels: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for ch in channels:
        cid = ch.get("id")
        if not cid:
            continue
        st = ch.get("statistics") or {}
        out[cid] = {
            "subscriberCount": st.get("subscriberCount"),
            "channel_viewCount": st.get("viewCount"),
            "videoCount": st.get("videoCount"),
            "channel_title": (ch.get("snippet") or {}).get("title"),
        }
    return out


def canonical_video_record(
    video_item: Dict[str, Any],
    *,
    provenance: str,
    channel_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Map a videos.list item toward the Stage 1 canonical entity shape .
    """
    sn = video_item.get("snippet") or {}
    st = video_item.get("statistics") or {}
    cd = video_item.get("contentDetails") or {}
    vid = video_item.get("id")
    channel_id = sn.get("channelId")
    title = sn.get("title") or ""
    desc = sn.get("description") or ""
    text = title if not desc else f"{title}\n{desc}"

    ctx: Dict[str, Any] = {}
    if channel_lookup and channel_id and channel_id in channel_lookup:
        ctx = dict(channel_lookup[channel_id])

    return {
        "platform": "YouTube",
        "post_id": vid,
        "author_id": channel_id,
        "community_channel_id": channel_id,
        "title_or_text": text,
        "url": f"https://www.youtube.com/watch?v={vid}" if vid else None,
        "created_at": sn.get("publishedAt"),
        "engagement": {
            "viewCount": st.get("viewCount"),
            "likeCount": st.get("likeCount"),
            "commentCount": st.get("commentCount"),
        },
        "content_details": {"duration": cd.get("duration")},
        "context_metrics": ctx,
        "provenance": provenance,
        "api_resource": "videos.list",
    }


def _safe_int(val: Any, default: int = 0) -> int:
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _truncate_label(text: str, max_len: int = 40) -> str:
    text = text or ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _figure_to_png_data_uri(fig: Any) -> str:
    """Serialize a matplotlib figure to a PNG data URI (no external files)."""
    import matplotlib.pyplot as plt

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    b64 = base64.standard_b64encode(buf.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _html_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    th = "".join(f"<th>{html_module.escape(h)}</th>" for h in headers)
    parts: List[str] = [f"<thead><tr>{th}</tr></thead><tbody>"]
    for row in rows:
        cells = "".join(f"<td>{html_module.escape(str(c))}</td>" for c in row)
        parts.append(f"<tr>{cells}</tr>")
    parts.append("</tbody>")
    return f"<table class='data'>{''.join(parts)}</table>"


def write_mentor_html_report(
    out_dir: Path,
    *,
    video_items: List[Dict[str, Any]],
    channel_items: List[Dict[str, Any]],
    enriched_videos: List[Dict[str, Any]],
    enriched_channels: List[Dict[str, Any]],
    search_query: str,
    search_raw_count: int,
) -> Path:
    """
    One-file HTML summary for reviewe: tables + matplotlib charts (embedded PNG).
    Opens in any browser; no extra viewer tools required.
    """

    curated_table_rows: List[List[str]] = []
    for v in video_items:
        flat = flatten_video_item(v)
        vid = flat.get("videoId") or ""
        curated_table_rows.append(
            [
                _truncate_label(flat.get("title") or "", 70),
                flat.get("channelTitle") or "",
                str(flat.get("viewCount") or "—"),
                flat.get("publishedAt") or "",
                f"https://www.youtube.com/watch?v={vid}" if vid else "",
            ]
        )

    channel_table_rows: List[List[str]] = []
    for ch in channel_items:
        f = flatten_channel_item(ch)
        channel_table_rows.append(
            [
                _truncate_label(f.get("title") or "", 55),
                str(f.get("customUrl") or "—"),
                str(f.get("subscriberCount") or "—"),
                str(f.get("videoCount") or "—"),
                f.get("channelId") or "",
            ]
        )

    search_table_rows: List[List[str]] = []
    for v in enriched_videos[:30]:
        flat = flatten_video_item(v)
        vid = flat.get("videoId") or ""
        search_table_rows.append(
            [
                _truncate_label(flat.get("title") or "", 65),
                flat.get("channelTitle") or "",
                str(flat.get("viewCount") or "—"),
                f"https://www.youtube.com/watch?v={vid}" if vid else "",
            ]
        )

    chart_blocks: List[str] = []
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        if video_items:
            labels = [
                _truncate_label((flatten_video_item(v).get("title") or "(no title)"), 34)
                for v in video_items
            ]
            views = [_safe_int((v.get("statistics") or {}).get("viewCount")) for v in video_items]
            fig_h = max(3.0, len(labels) * 0.38)
            fig, ax = plt.subplots(figsize=(10, fig_h))
            y_pos = range(len(labels))
            ax.barh(list(y_pos), views, color="#1d4ed8")
            ax.set_yticks(list(y_pos))
            ax.set_yticklabels(labels, fontsize=8)
            ax.set_xlabel("View count")
            ax.set_title("Curated videos (videos.list)")
            ax.invert_yaxis()
            uri = _figure_to_png_data_uri(fig)
            chart_blocks.append(
                f"<section class='chart'><h2>Curated videos — view counts</h2>"
                f"<img src='{uri}' alt='Bar chart of view counts'/></section>"
            )

        if channel_items:
            labels_ch = [
                _truncate_label((flatten_channel_item(c).get("title") or "(channel)"), 34)
                for c in channel_items
            ]
            subs = [_safe_int((c.get("statistics") or {}).get("subscriberCount")) for c in channel_items]
            fig_h = max(3.0, len(labels_ch) * 0.38)
            fig2, ax2 = plt.subplots(figsize=(10, fig_h))
            y2 = range(len(labels_ch))
            ax2.barh(list(y2), subs, color="#047857")
            ax2.set_yticks(list(y2))
            ax2.set_yticklabels(labels_ch, fontsize=8)
            ax2.set_xlabel("Subscriber count (hidden → 0)")
            ax2.set_title("Curated channels (channels.list)")
            ax2.invert_yaxis()
            uri2 = _figure_to_png_data_uri(fig2)
            chart_blocks.append(
                f"<section class='chart'><h2>Curated channels — subscribers</h2>"
                f"<img src='{uri2}' alt='Bar chart of subscriber counts'/></section>"
            )

        ranked = sorted(
            enriched_videos,
            key=lambda v: _safe_int((v.get("statistics") or {}).get("viewCount")),
            reverse=True,
        )[:15]
        if ranked:
            labels_s = [
                _truncate_label((flatten_video_item(v).get("title") or "(video)"), 32) for v in ranked
            ]
            views_s = [_safe_int((v.get("statistics") or {}).get("viewCount")) for v in ranked]
            fig3, ax3 = plt.subplots(figsize=(10, max(3.0, len(labels_s) * 0.38)))
            y3 = range(len(labels_s))
            ax3.barh(list(y3), views_s, color="#b45309")
            ax3.set_yticks(list(y3))
            ax3.set_yticklabels(labels_s, fontsize=8)
            ax3.set_xlabel("View count")
            ax3.set_title(f'Top search results by views — query: {search_query!r}')
            ax3.invert_yaxis()
            uri3 = _figure_to_png_data_uri(fig3)
            chart_blocks.append(
                f"<section class='chart'><h2>Search enrichment — top videos by views</h2>"
                f"<img src='{uri3}' alt='Bar chart of search result views'/></section>"
            )
    except ImportError:
        logging.warning(
            "matplotlib not installed; HTML report will contain tables only. "
            "Install with: python -m pip install matplotlib"
        )

    charts_html = "\n".join(chart_blocks) if chart_blocks else (
        "<p class='note'>Charts omitted (install <code>matplotlib</code> for bar charts).</p>"
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Stage 1 — YouTube API ingest summary</title>
  <style>
    :root {{ font-family: "Segoe UI", system-ui, sans-serif; color: #0f172a; }}
    body {{ max-width: 1100px; margin: 2rem auto; padding: 0 1.25rem; line-height: 1.45; }}
    h1 {{ font-size: 1.55rem; border-bottom: 2px solid #1d4ed8; padding-bottom: 0.35rem; }}
    h2 {{ font-size: 1.1rem; margin-top: 2rem; color: #1e293b; }}
    .meta {{ color: #475569; font-size: 0.9rem; margin: 0.5rem 0 1.25rem; }}
    table.data {{ border-collapse: collapse; width: 100%; font-size: 0.82rem; }}
    table.data th, table.data td {{ border: 1px solid #e2e8f0; padding: 0.45rem 0.5rem; vertical-align: top; }}
    table.data th {{ background: #f1f5f9; text-align: left; }}
    table.data tr:nth-child(even) {{ background: #f8fafc; }}
    section.chart img {{ max-width: 100%; height: auto; border: 1px solid #e2e8f0; border-radius: 6px; }}
    .note {{ background: #fff7ed; border: 1px solid #fed7aa; padding: 0.75rem 1rem; border-radius: 6px; }}
    a {{ color: #1d4ed8; }}
  </style>
</head>
<body>
  <h1>Stage 1 — YouTube Data API v3 ingest (results summary)</h1>
  <p class="meta">Public API key ingestion · Endpoints: <code>videos.list</code>, <code>channels.list</code>, <code>search.list</code>
  (then mandatory <code>videos.list</code> + <code>channels.list</code> on search hits).</p>
  <p class="meta">Topic search query: <strong>{html_module.escape(search_query)}</strong> ·
  Raw search results: <strong>{search_raw_count}</strong> ·
  Enriched videos: <strong>{len(enriched_videos)}</strong> ·
  Enriched channels: <strong>{len(enriched_channels)}</strong></p>

  <h2>Curated videos (mentor list)</h2>
  {_html_table(["Title", "Channel", "Views", "Published", "URL"], curated_table_rows)}

  <h2>Curated channels</h2>
  {_html_table(["Title", "Custom URL", "Subscribers", "Video count", "Channel ID"], channel_table_rows)}

  <h2>Search results (enriched via videos.list) — first 30</h2>
  {_html_table(["Title", "Channel", "Views", "URL"], search_table_rows)}

  {charts_html}

  <p class="meta" style="margin-top:2rem;">Raw JSON/CSV/JSONL exports are in the same output folder as this file.</p>
</body>
</html>
"""

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "out_stage1_report.html"
    path.write_text(html, encoding="utf-8")
    return path


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Ingest public YouTube metadata via Data API v3 (Stage 1 alignment).",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("."),
        help="Directory for JSON/CSV/JSONL outputs (default: current directory).",
    )
    p.add_argument(
        "--search-query",
        default="critical thinking",
        help='search.list query string (default: "critical thinking").',
    )
    p.add_argument(
        "--search-pages",
        type=int,
        default=2,
        help="Max pages of search.list pagination (default: 2).",
    )
    p.add_argument(
        "--search-page-size",
        type=int,
        default=25,
        help="search.list maxResults per page (default: 25, max 50).",
    )
    p.add_argument(
        "--api-key-env",
        default="YOUTUBE_API_KEY",
        help="Environment variable name holding the API key (default: YOUTUBE_API_KEY).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="DEBUG logging.")
    p.add_argument(
        "--no-html-report",
        action="store_true",
        help="Skip writing out_stage1_mentor_report.html (tables + charts).",
    )
    p.add_argument(
        "--open-report",
        action="store_true",
        help="After success, open the HTML report in the default browser.",
    )
    return p.parse_args(argv)


def run_ingestion(cfg: IngestConfig) -> Optional[Path]:
    api_key = os.environ.get(cfg.api_key_env, "").strip()
    if not api_key:
        logging.error(
            "Missing API key: set %s (public Data API v3 key; OAuth not used for this job).",
            cfg.api_key_env,
        )
        raise SystemExit(2)

    session = requests.Session()
    session.headers["User-Agent"] = cfg.user_agent

    client = YouTubeApiClient(
        api_key=api_key,
        session=session,
        request_delay_s=cfg.request_delay_s,
    )
    out = cfg.output_dir

    # --- 1) Curated videos: ID-driven videos.list (quota-efficient) ---
    video_ids = [extract_video_id(u) for u in VIDEO_URLS]
    video_items = videos_list(client, video_ids)
    write_json(out / "out_videos_raw.json", {"items": video_items})
    write_csv_flat(
        out / "out_videos_flat.csv",
        [flatten_video_item(i) for i in video_items],
        [
            "videoId",
            "channelId",
            "channelTitle",
            "title",
            "publishedAt",
            "duration",
            "viewCount",
            "likeCount",
            "commentCount",
        ],
    )
    logging.info("Curated videos: fetched %s / %s", len(video_items), len(video_ids))

    # --- 2) Curated channels: search.list(type=channel) then channels.list ---
    resolved_ids, failures = resolve_channel_ids_via_search(client, CHANNEL_HANDLES)
    for h, reason in failures:
        logging.warning("Channel handle resolve failed: %s — %s", h, reason)

    channel_items = channels_list(client, resolved_ids)
    write_json(
        out / "out_channels_raw.json",
        {"items": channel_items, "resolved_from_handles": CHANNEL_HANDLES},
    )
    write_csv_flat(
        out / "out_channels_flat.csv",
        [flatten_channel_item(i) for i in channel_items],
        [
            "channelId",
            "title",
            "customUrl",
            "publishedAt",
            "country",
            "subscriberCount",
            "viewCount",
            "videoCount",
        ],
    )
    logging.info(
        "Curated channels: fetched %s channels (%s IDs resolved)",
        len(channel_items),
        len(resolved_ids),
    )

    curated_channel_lookup = channel_context_by_id(channel_items)
    write_jsonl(
        out / "out_canonical_curated_videos.jsonl",
        (
            canonical_video_record(
                v,
                provenance="curated_mentor_list",
                channel_lookup=curated_channel_lookup,
            )
            for v in video_items
        ),
    )

    # --- 3) Topic search + mandatory videos.list + channels.list enrichment ---
    search_items = search_videos(
        client,
        cfg.search_query,
        cfg.search_max_pages,
        min(cfg.search_page_size, 50),
    )
    write_json(
        out / "out_search_raw.json",
        {"items": search_items, "query": cfg.search_query},
    )
    logging.info("Search %r: %s raw hits", cfg.search_query, len(search_items))

    search_video_ids: List[str] = []
    for it in search_items:
        vid = (it.get("id") or {}).get("videoId")
        if vid:
            search_video_ids.append(vid)
    search_video_ids = list(dict.fromkeys(search_video_ids))
    enriched_videos = videos_list(client, search_video_ids)
    write_json(out / "out_search_enriched_videos.json", {"items": enriched_videos})

    search_channel_ids: List[str] = []
    for it in search_items:
        cid = (it.get("snippet") or {}).get("channelId")
        if cid:
            search_channel_ids.append(cid)
    for v in enriched_videos:
        cid = (v.get("snippet") or {}).get("channelId")
        if cid:
            search_channel_ids.append(cid)
    search_channel_ids = list(dict.fromkeys(search_channel_ids))
    enriched_channels = channels_list(client, search_channel_ids)
    write_json(out / "out_search_enriched_channels.json", {"items": enriched_channels})
    write_csv_flat(
        out / "out_search_enriched_channels_flat.csv",
        [flatten_channel_item(i) for i in enriched_channels],
        [
            "channelId",
            "title",
            "customUrl",
            "publishedAt",
            "country",
            "subscriberCount",
            "viewCount",
            "videoCount",
        ],
    )

    search_channel_lookup = channel_context_by_id(enriched_channels)
    write_jsonl(
        out / "out_canonical_search_videos.jsonl",
        (
            canonical_video_record(
                v,
                provenance=f"search:{cfg.search_query}",
                channel_lookup=search_channel_lookup,
            )
            for v in enriched_videos
        ),
    )

    logging.info(
        "Search enrichment: %s videos (videos.list), %s channels (channels.list)",
        len(enriched_videos),
        len(enriched_channels),
    )

    report_path: Optional[Path] = None
    if cfg.generate_html_report:
        report_path = write_mentor_html_report(
            out,
            video_items=video_items,
            channel_items=channel_items,
            enriched_videos=enriched_videos,
            enriched_channels=enriched_channels,
            search_query=cfg.search_query,
            search_raw_count=len(search_items),
        )
        logging.info("Mentor HTML report written: %s", report_path)
    return report_path


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)
    cfg = IngestConfig(
        output_dir=args.out_dir.resolve(),
        api_key_env=args.api_key_env,
        search_query=args.search_query,
        search_max_pages=args.search_pages,
        search_page_size=min(max(1, args.search_page_size), 50),
    )
    run_ingestion(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
