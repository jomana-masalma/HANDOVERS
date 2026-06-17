"""
Optional enrichment — captions/transcripts (when permitted).

Important reality check (why this is optional):
- With an API key alone, YouTube does NOT provide transcript text.
- Caption track access typically requires OAuth and depends on whether captions exist and
  whether the authenticated account has permission to access/download them.

This script uses the official YouTube Data API client (OAuth flow) to:
1) list available caption tracks for each video (`captions.list`)
2) download a chosen caption track (`captions.download`) into `youtube_out/captions/`


"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# These packages are only needed if you run this script.
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


@dataclass
class TranscriptConfig:
    out_dir: Path = field(default_factory=lambda: Path("./youtube_out"))
    client_secrets: Path = field(default_factory=lambda: Path("./client_secrets.json"))
    token_path: Path = field(default_factory=lambda: Path("./oauth_token.json"))
    max_videos: int = 10
    preferred_languages: List[str] = field(default_factory=lambda: ["en", "en-US", "en-GB"])


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def read_stage1_video_ids(out_dir: Path) -> List[str]:
    """
    Reuse Stage 1 outputs so we don't require retyping IDs.
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
            return list(dict.fromkeys(ids))
    return []


def build_youtube_service(cfg: TranscriptConfig):
    """
    OAuth interactive flow.
    Why: captions endpoints are not available via simple API key authentication.
    """
    if not cfg.client_secrets.exists():
        raise SystemExit(
            "Missing OAuth client secrets file. Provide --client-secrets path to client_secrets.json."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(cfg.client_secrets), SCOPES)
    creds = flow.run_local_server(port=0)
    # Save token for reuse (so you don't re-auth each time).
    cfg.token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def choose_caption_track(items: List[Dict[str, Any]], preferred_languages: List[str]) -> Optional[Dict[str, Any]]:
    """
    Pick one caption track to download.
    Simple selection logic:
    - Prefer a track with language in preferred_languages
    - Otherwise take the first track
    """
    by_lang = {it.get("snippet", {}).get("language"): it for it in items}
    for lang in preferred_languages:
        if lang in by_lang:
            return by_lang[lang]
    return items[0] if items else None


def run(cfg: TranscriptConfig) -> None:
    video_ids = read_stage1_video_ids(cfg.out_dir)[: max(cfg.max_videos, 0)]
    if not video_ids:
        raise SystemExit(
            f"No video IDs found in {cfg.out_dir}. Run Stage 1 first (or place outputs in youtube_out/)."
        )

    yt = build_youtube_service(cfg)

    captions_dir = cfg.out_dir / "captions"
    captions_dir.mkdir(parents=True, exist_ok=True)

    index: Dict[str, Any] = {"videos": {}}

    for vid in video_ids:
        logging.info("Listing caption tracks for videoId=%s", vid)
        try:
            resp = yt.captions().list(part="snippet", videoId=vid).execute()
        except HttpError as e:
            # Many videos will fail here due to permissions or missing captions.
            logging.warning("captions.list failed for %s: %s", vid, str(e)[:300])
            index["videos"][vid] = {"error": str(e), "tracks": []}
            continue

        items = resp.get("items", []) or []
        index["videos"][vid] = {"tracks": items}
        chosen = choose_caption_track(items, cfg.preferred_languages)
        if not chosen:
            logging.info("No caption tracks found for %s", vid)
            continue

        cap_id = chosen.get("id")
        lang = (chosen.get("snippet") or {}).get("language") or "unknown"
        out_path = captions_dir / f"{vid}.{lang}.vtt"

        logging.info("Downloading captions: videoId=%s captionId=%s lang=%s", vid, cap_id, lang)
        try:
            # Download as WebVTT (easy to parse later).
            data = (
                yt.captions()
                .download(id=cap_id, tfmt="vtt")
                .execute()
            )
            # googleapiclient can return bytes; normalize to text.
            if isinstance(data, bytes):
                out_path.write_bytes(data)
            else:
                out_path.write_text(str(data), encoding="utf-8")
            index["videos"][vid]["downloaded"] = {"captionId": cap_id, "path": str(out_path)}
        except HttpError as e:
            logging.warning("captions.download failed for %s: %s", vid, str(e)[:300])
            index["videos"][vid]["download_error"] = str(e)

    (cfg.out_dir / "out_captions_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logging.info("Done. Wrote captions index: %s", cfg.out_dir / "out_captions_index.json")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Optional: captions/transcripts via OAuth (when permitted).")
    p.add_argument("--out-dir", type=Path, default=Path("./youtube_out"))
    p.add_argument("--client-secrets", type=Path, required=True, help="Path to OAuth client_secrets.json")
    p.add_argument("--token-path", type=Path, default=Path("./oauth_token.json"))
    p.add_argument("--max-videos", type=int, default=10)
    p.add_argument("--preferred-language", action="append", default=[], help="Repeatable (e.g. --preferred-language en)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)
    cfg = TranscriptConfig(
        out_dir=args.out_dir.resolve(),
        client_secrets=args.client_secrets.resolve(),
        token_path=args.token_path.resolve(),
        max_videos=max(args.max_videos, 0),
        preferred_languages=args.preferred_language or ["en", "en-US", "en-GB"],
    )
    run(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

