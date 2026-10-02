"""
Read-only Streamlit dashboard.
Loads saved files from youtube_out/; does NOT call the YouTube API.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st


#  so it runs without extra config.
DEFAULT_OUT_DIR = Path("./youtube_out")


def _read_json_items(path: Path) -> List[Dict[str, Any]]:
    # Stage 1 saves {"items": [...]} — we only need the list for tables/charts.
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", [])
    if not isinstance(items, list):
        return []
    return items


def _safe_int(x: Any) -> Optional[int]:
    if x is None or x == "":
        return None
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _flatten_video(item: Dict[str, Any]) -> Dict[str, Any]:
    sn = item.get("snippet") or {}
    stt = item.get("statistics") or {}
    cd = item.get("contentDetails") or {}
    vid = item.get("id")
    return {
        "videoId": vid,
        "title": sn.get("title"),
        "channelTitle": sn.get("channelTitle"),
        "channelId": sn.get("channelId"),
        "publishedAt": sn.get("publishedAt"),
        "duration": cd.get("duration"),
        "viewCount": _safe_int(stt.get("viewCount")),
        "likeCount": _safe_int(stt.get("likeCount")),
        "commentCount": _safe_int(stt.get("commentCount")),
        "url": f"https://www.youtube.com/watch?v={vid}" if vid else None,
    }


def _flatten_channel(item: Dict[str, Any]) -> Dict[str, Any]:
    sn = item.get("snippet") or {}
    stt = item.get("statistics") or {}
    cid = item.get("id")
    custom = sn.get("customUrl")
    return {
        "channelId": cid,
        "title": sn.get("title"),
        "customUrl": custom,
        "publishedAt": sn.get("publishedAt"),
        "country": sn.get("country"),
        "subscriberCount": _safe_int(stt.get("subscriberCount")),
        "viewCount": _safe_int(stt.get("viewCount")),
        "videoCount": _safe_int(stt.get("videoCount")),
        "url": f"https://www.youtube.com/{custom}" if custom else None,
    }


def load_outputs(out_dir: Path) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    # Read the three main Stage 1 JSON outputs and flatten to pandas for Streamlit.
    curated_videos = _read_json_items(out_dir / "out_videos_raw.json")
    curated_channels = _read_json_items(out_dir / "out_channels_raw.json")
    search_raw = json.loads((out_dir / "out_search_raw.json").read_text(encoding="utf-8")) if (out_dir / "out_search_raw.json").exists() else {}
    query = search_raw.get("query") or ""
    search_enriched_videos = _read_json_items(out_dir / "out_search_enriched_videos.json")

    df_videos = pd.DataFrame([_flatten_video(v) for v in curated_videos])
    df_channels = pd.DataFrame([_flatten_channel(c) for c in curated_channels])
    df_search = pd.DataFrame([_flatten_video(v) for v in search_enriched_videos])

    # Normalize types
    for df in (df_videos, df_search):
        for col in ["viewCount", "likeCount", "commentCount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
    if "subscriberCount" in df_channels.columns:
        df_channels["subscriberCount"] = pd.to_numeric(df_channels["subscriberCount"], errors="coerce")

    return df_videos, df_channels, df_search, str(query)


def main() -> None:
    st.set_page_config(page_title="Stage 1 — YouTube Dashboard", layout="wide")

    st.title("Stage 1 — YouTube API Results Dashboard")
    st.caption("Reads outputs from your ingestion run (no API calls here).")

    with st.sidebar:
        st.header("Data folder")
        out_dir_str = st.text_input("Output folder", value=str(DEFAULT_OUT_DIR))
        out_dir = Path(out_dir_str)
        st.write("Expected files:")
        st.code(
            "\n".join(
                [
                    "out_videos_raw.json",
                    "out_channels_raw.json",
                    "out_search_raw.json",
                    "out_search_enriched_videos.json",
                    "out_search_enriched_channels.json (optional here)",
                ]
            )
        )
        reload_clicked = st.button("Reload data")

    if reload_clicked:
        # After a new ingest run, clear cache so the dashboard picks up fresh files.
        st.cache_data.clear()

    @st.cache_data(show_spinner=False)
    def _cached_load(p: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
        # Cache avoids re-parsing large JSON on every sidebar interaction.
        return load_outputs(Path(p))

    if not out_dir.exists():
        st.error(f"Folder not found: {out_dir.resolve()}")
        st.stop()

    df_videos, df_channels, df_search, query = _cached_load(str(out_dir))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Curated videos", int(df_videos.shape[0]))
    c2.metric("Curated channels", int(df_channels.shape[0]))
    c3.metric("Search enriched videos", int(df_search.shape[0]))
    c4.metric("Search query", query or "—")

    st.divider()

    tab1, tab2, tab3 = st.tabs(["Curated videos", "Curated channels", "Search results"])

    with tab1:
        st.subheader("Curated videos (from fixed list, curted videos)")
        if df_videos.empty:
            st.warning("No curated video data found. Run the ingestion script first.")
        else:
            min_views, max_views = int(df_videos["viewCount"].fillna(0).min()), int(df_videos["viewCount"].fillna(0).max())
            view_range = st.slider("Filter by views", min_views, max_views, (min_views, max_views))
            df = df_videos.copy()
            df = df[df["viewCount"].fillna(0).between(view_range[0], view_range[1])]
            st.dataframe(
                df.sort_values("viewCount", ascending=False),
                use_container_width=True,
                column_config={
                    "url": st.column_config.LinkColumn("URL"),
                },
            )
            st.bar_chart(df.set_index("title")["viewCount"].fillna(0).sort_values(ascending=False).head(15))

    with tab2:
        st.subheader("Curated channels")
        if df_channels.empty:
            st.warning("No curated channel data found. Run the ingestion script first.")
        else:
            st.dataframe(
                df_channels.sort_values("subscriberCount", ascending=False),
                use_container_width=True,
                column_config={
                    "url": st.column_config.LinkColumn("URL"),
                },
            )
            if "subscriberCount" in df_channels.columns:
                st.bar_chart(df_channels.set_index("title")["subscriberCount"].fillna(0).sort_values(ascending=False).head(15))

    with tab3:
        st.subheader("Search results (enriched via videos.list)")
        if df_search.empty:
            st.warning("No search enriched video data found. Run the ingestion script first.")
        else:
            sort_by = st.selectbox("Sort by", ["viewCount", "likeCount", "commentCount", "publishedAt"], index=0)
            df = df_search.copy()
            if sort_by in ["viewCount", "likeCount", "commentCount"]:
                df = df.sort_values(sort_by, ascending=False)
            else:
                df = df.sort_values(sort_by, ascending=False)
            st.dataframe(
                df,
                use_container_width=True,
                column_config={
                    "url": st.column_config.LinkColumn("URL"),
                },
            )
            st.bar_chart(df.set_index("title")["viewCount"].fillna(0).sort_values(ascending=False).head(20))

    st.divider()
    st.caption("Tip: First run `python youtube_ingest_stage1.py --out-dir ./youtube_out` to create the data files.")


if __name__ == "__main__":
    main()

