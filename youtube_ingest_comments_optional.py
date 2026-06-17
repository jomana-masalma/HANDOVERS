"""
Optional enrichment — download public YouTube comments (thread roots + replies).

Why this is a separate script (not Stage 1):
- Stage 1 was kept small/quota-aware and only stored `commentCount` (an integer per video).
- Comments can be large and can consume more quota, so this script makes the scope explicit
  and supports strict limits (`--max-videos`, `--max-comments-per-video`).

Auth model:
- Uses the same API-key approach as Stage 1 (environment variable `YOUTUBE_API_KEY`).
- Only accesses public comment threads via `commentThreads.list`.

Outputs (written under the chosen --out-dir):
- `out_commentthreads_raw.json`  (raw API payloads per video)
- `out_commentthreads_flat.csv`  (flat table for quick analysis)
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


@dataclass
class CommentConfig:
    out_dir: Path = field(default_factory=lambda: Path("./youtube_out"))
    api_key_env: str = "YOUTUBE_API_KEY"
    max_videos: int = 10
    max_comments_per_video: int = 200
    include_replies: bool = True
    order: str = "relevance"  # "time" is also valid
    page_size: int = 100  # API max is 100 for commentThreads
    request_delay_s: float = 0.05


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


@dataclass(frozen=True)
class YouTubeApiClient:
    # Keep API behavior consistent with Stage 1 (single request wrapper).
    api_key: str
    session: requests.Session
    request_delay_s: float

    def get(self, resource: str, params: Dict[str, Any]) -> Dict[str, Any]:
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
            raise RuntimeError(f"HTTP {r.status_code} for {resource}: {json.dumps(payload)[:2000]}")
        if self.request_delay_s > 0:
            time.sleep(self.request_delay_s)
        return r.json()


def read_stage1_video_ids(out_dir: Path) -> List[str]:
    """
    Prefer Stage 1 curated videos output. This avoids requiring the user to retype IDs.
    Falls back to search-enriched videos if curated is missing.
    """
    candidates = [
        out_dir / "out_videos_raw.json",
        out_dir / "out_search_enriched_videos.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data.get("items", [])
        ids = [it.get("id") for it in items if isinstance(it, dict) and it.get("id")]
        if ids:
            # Keep unique order.
            return list(dict.fromkeys(ids))
    return []


def iter_commentthreads(
    client: YouTubeApiClient,
    *,
    video_id: str,
    include_replies: bool,
    order: str,
    page_size: int,
    max_threads: int,
) -> Iterable[Dict[str, Any]]:
    """
    Generator over commentThreads.list pages.

    Why page tokens:
    - Comment threads are paginated. We stop early after max_threads to control quota/time.
    """
    page_token: Optional[str] = None
    seen = 0
    while True:
        params: Dict[str, Any] = {
            "part": "snippet,replies" if include_replies else "snippet",
            "videoId": video_id,
            "maxResults": min(max(page_size, 1), 100),
            "order": order,
            "textFormat": "plainText",
        }
        if page_token:
            params["pageToken"] = page_token
        payload = client.get("commentThreads", params)
        for item in payload.get("items", []) or []:
            yield item
            seen += 1
            if seen >= max_threads:
                return
        page_token = payload.get("nextPageToken")
        if not page_token:
            return


def flatten_thread(video_id: str, thread: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert one thread (top-level + replies) into flat rows.
    Keeping it flat makes it easy to load into pandas / CSV / SQL later.
    """
    rows: List[Dict[str, Any]] = []

    sn = (thread.get("snippet") or {}).get("topLevelComment") or {}
    sn_snip = sn.get("snippet") or {}
    top_id = sn.get("id")
    rows.append(
        {
            "videoId": video_id,
            "commentId": top_id,
            "parentCommentId": "",
            "authorChannelId": ((sn_snip.get("authorChannelId") or {}).get("value") or ""),
            "authorDisplayName": sn_snip.get("authorDisplayName") or "",
            "publishedAt": sn_snip.get("publishedAt") or "",
            "likeCount": sn_snip.get("likeCount") or 0,
            "text": (sn_snip.get("textDisplay") or "").replace("\n", " ").strip(),
        }
    )

    replies = (thread.get("replies") or {}).get("comments") or []
    for r in replies:
        r_snip = (r.get("snippet") or {})
        rows.append(
            {
                "videoId": video_id,
                "commentId": r.get("id") or "",
                "parentCommentId": top_id or "",
                "authorChannelId": ((r_snip.get("authorChannelId") or {}).get("value") or ""),
                "authorDisplayName": r_snip.get("authorDisplayName") or "",
                "publishedAt": r_snip.get("publishedAt") or "",
                "likeCount": r_snip.get("likeCount") or 0,
                "text": (r_snip.get("textDisplay") or "").replace("\n", " ").strip(),
            }
        )

    return rows


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Dict[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fieldnames))
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def run(cfg: CommentConfig) -> None:
    api_key = os.environ.get(cfg.api_key_env, "").strip()
    if not api_key:
        raise SystemExit(f"Missing API key: set {cfg.api_key_env} before running this script.")

    video_ids = read_stage1_video_ids(cfg.out_dir)[: max(cfg.max_videos, 0)]
    if not video_ids:
        raise SystemExit(
            f"No video IDs found in {cfg.out_dir}. Run Stage 1 first (or place outputs in youtube_out/)."
        )

    sess = requests.Session()
    client = YouTubeApiClient(api_key=api_key, session=sess, request_delay_s=cfg.request_delay_s)

    raw_out: Dict[str, Any] = {"videos": {}}
    flat_rows: List[Dict[str, Any]] = []

    for vid in video_ids:
        logging.info("Fetching comments for videoId=%s", vid)
        threads = list(
            iter_commentthreads(
                client,
                video_id=vid,
                include_replies=cfg.include_replies,
                order=cfg.order,
                page_size=cfg.page_size,
                max_threads=cfg.max_comments_per_video,
            )
        )
        raw_out["videos"][vid] = {"thread_count": len(threads), "items": threads}
        for t in threads:
            flat_rows.extend(flatten_thread(vid, t))

    write_json(cfg.out_dir / "out_commentthreads_raw.json", raw_out)
    write_csv(
        cfg.out_dir / "out_commentthreads_flat.csv",
        flat_rows,
        [
            "videoId",
            "commentId",
            "parentCommentId",
            "authorChannelId",
            "authorDisplayName",
            "publishedAt",
            "likeCount",
            "text",
        ],
    )
    logging.info("Done. Wrote %s rows.", len(flat_rows))


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Optional: download public comment threads for Stage 1 videos.")
    p.add_argument("--out-dir", type=Path, default=Path("./youtube_out"))
    p.add_argument("--api-key-env", default="YOUTUBE_API_KEY")
    p.add_argument("--max-videos", type=int, default=10)
    p.add_argument("--max-comments-per-video", type=int, default=200)
    p.add_argument("--no-replies", action="store_true", help="Only top-level comments (skip replies).")
    p.add_argument("--order", default="relevance", choices=["relevance", "time"])
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)
    cfg = CommentConfig(
        out_dir=args.out_dir.resolve(),
        api_key_env=args.api_key_env,
        max_videos=max(args.max_videos, 0),
        max_comments_per_video=max(args.max_comments_per_video, 0),
        include_replies=not args.no_replies,
        order=args.order,
    )
    run(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

