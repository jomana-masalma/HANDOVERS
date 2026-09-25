"""
Stage 1 ingest for the curated videos and channels.

Uses the official YouTube Data API v3: videos.list, channels.list, and search.list.
Public read with an API key. Does not download media.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

# Curated video URLs used as fixed Stage 1 seed inputs.
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

# Curated channel handles that must be resolved to channel IDs via search.
CHANNEL_HANDLES: List[str] = [
    "@TEDEd",
    "@CasuallyExplained",
    "@TEDx",
    "@bbcideas",
    "@WirelessPhilosophy",
]

# Request broad video metadata in one API roundtrip per batch.
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

# Request broad channel metadata for enrichment and context metrics.
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

# search.list supports snippet for discovery metadata.
SEARCH_PARTS = "snippet"

# Parse 11-char video IDs from standard watch URLs.
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
    api_key: str
    session: requests.Session
    request_delay_s: float

    def get(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
        # Build endpoint URL and attach API key to each request.
        url = f"{YOUTUBE_API_BASE}/{resource.lstrip('/')}"
        q = dict(params)
        q["key"] = self.api_key

        # Log request metadata without exposing the key.
        logging.debug("GET %s params=%s", resource, {k: v for k, v in q.items() if k != "key"})
        r = self.session.get(url, params=q, timeout=60)

        # Fail fast with API payload detail when response is not OK.
        if r.status_code != 200:
            try:
                payload = r.json()
            except Exception:
                payload = {"text": r.text}
            raise RuntimeError(
                f"HTTP {r.status_code} for {resource}: "
                f"{json.dumps(payload, ensure_ascii=False)[:2000]}"
            )

        # Add a small pause between calls to avoid rapid bursts of requests
        if self.request_delay_s > 0:
            time.sleep(self.request_delay_s)
        return r.json()


def chunked(seq: Sequence[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(seq), n):
        yield list(seq[i : i + n])


def videos_list(client: YouTubeApiClient, video_ids: Sequence[str]) -> List[Dict[str, Any]]:
    # Batch IDs to API max size (50) for quota-efficient retrieval.
    items: List[Dict[str, Any]] = []
    for batch in chunked(list(video_ids), 50):
        data = client.get(
            "videos",
            {"part": VIDEO_PARTS, "id": ",".join(batch), "maxResults": 50},
        )
        items.extend(data.get("items", []))
    return items


def channels_list(client: YouTubeApiClient, channel_ids: Sequence[str]) -> List[Dict[str, Any]]:
    # Batch channel IDs to API max size (50) to reduce total calls.
    items: List[Dict[str, Any]] = []
    for batch in chunked(list(channel_ids), 50):
        data = client.get(
            "channels",
            {"part": CHANNEL_PARTS, "id": ",".join(batch), "maxResults": 50},
        )
        items.extend(data.get("items", []))
    return items


def resolve_channel_ids_via_search(
    client: YouTubeApiClient, handles: Sequence[str]
) -> Tuple[List[str], List[Tuple[str, str]]]:
    channel_ids: List[str] = []
    failures: List[Tuple[str, str]] = []

    for h in handles:
        # Normalize @handle so search query stays clean.
        q = h.lstrip("@").strip()
        if not q:
            failures.append((h, "empty handle"))
            continue

        # Resolve handle-like text to channel search hits.
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

        # Pick first hit's channelId as ID for subsequent channels.list calls.
        cid = (found[0].get("id") or {}).get("channelId")
        if not cid:
            failures.append((h, "search result missing channelId"))
            continue
        channel_ids.append(cid)

    # De-duplicate while preserving order.
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
    # Discover candidate videos with controlled pagination limits.
    items: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    for _ in range(max_pages):
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
    # Ensure output folder exists before writing JSON snapshots.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv_flat(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    # Write deterministic CSV columns for analyst-friendly tabular review.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    # Emit one-record-per-line JSON for pipeline and streaming compatibility.
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
    # Build quick channel lookup so video records can be enriched cheaply.
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
    Map a videos.list item toward the Stage 1 canonical entity shape (platform-agnostic names).
    """
    sn = video_item.get("snippet") or {}
    st = video_item.get("statistics") or {}
    cd = video_item.get("contentDetails") or {}
    vid = video_item.get("id")
    channel_id = sn.get("channelId")
    title = sn.get("title") or ""
    desc = sn.get("description") or ""
    text = title if not desc else f"{title}\n{desc}"

    # Pull channel context if available to enrich canonical output.
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


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    # Define CLI controls so behavior can be tuned without code edits.
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
    return p.parse_args(argv)


def run_ingestion(cfg: IngestConfig) -> None:
    # Read API key from environment and stop early if missing.
    api_key = os.environ.get(cfg.api_key_env, "").strip()
    if not api_key:
        logging.error(
            "Missing API key: set %s (public Data API v3 key; OAuth not used for this job).",
            cfg.api_key_env,
        )
        raise SystemExit(2)

    # Prepare shared HTTP session and identify this client with User-Agent.
    session = requests.Session()
    session.headers["User-Agent"] = cfg.user_agent

    # Create typed API client used by all endpoint helper calls.
    client = YouTubeApiClient(
        api_key=api_key,
        session=session,
        request_delay_s=cfg.request_delay_s,
    )
    out = cfg.output_dir

    # Stage 1A: fetch curated video metadata from known IDs.
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

    # Stage 1B: resolve channel handles, then fetch full channel metadata.
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

    # Build canonical JSONL for curated videos using channel context metrics.
    curated_channel_lookup = channel_context_by_id(channel_items)
    write_jsonl(
        out / "out_canonical_curated_videos.jsonl",
        (
            canonical_video_record(
                v,
                provenance="curated_list",
                channel_lookup=curated_channel_lookup,
            )
            for v in video_items
        ),
    )

    # Stage 1C: discover topic videos via search, then enrich using list endpoints.
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

    # Extract unique video IDs from search results for full video enrichment.
    search_video_ids: List[str] = []
    for it in search_items:
        vid = (it.get("id") or {}).get("videoId")
        if vid:
            search_video_ids.append(vid)
    search_video_ids = list(dict.fromkeys(search_video_ids))
    enriched_videos = videos_list(client, search_video_ids)
    write_json(out / "out_search_enriched_videos.json", {"items": enriched_videos})

    # Extract unique channel IDs from search + videos, then enrich channels.
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

    # Build canonical JSONL for search-discovered enriched videos.
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

    return None


def main() -> int:
    # Parse CLI args and configure log level first.
    args = parse_args()
    setup_logging(args.verbose)

    # Build runtime config object from validated CLI values.
    cfg = IngestConfig(
        output_dir=args.out_dir.resolve(),
        api_key_env=args.api_key_env,
        search_query=args.search_query,
        search_max_pages=args.search_pages,
        search_page_size=min(max(1, args.search_page_size), 50),
    )

    # Execute ingestion pipeline.
    run_ingestion(cfg)
    return 0


if __name__ == "__main__":
    # Keep command-line exit behavior explicit.
    raise SystemExit(main())
