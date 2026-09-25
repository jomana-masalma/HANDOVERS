"""
Streamlit — **Final video-IDs visualization** (read-only dashboard).

Shows **exactly what is on disk** for the 10 curated videos:

- **Stage 1A metadata** — ``videos.list``: views, likes, **commentCount** (YouTube headline stat, not rows ingested).
- **Stage 1 comments** — first-pass ``out_video_comments.jsonl`` (top + reply **rows**).
- **Round 2** — incremental folder (may be empty if run stopped early).
- **Round 3** — deeper incremental **new** rows only.
- **Cumulative** — unique ``commentId`` union (stage 1 ∪ round 3; round 2 if any).
- **Transcripts** — ``out_video_transcripts.json`` when present.

No API calls. No invented counts.

**Layout (algae-dashboard pattern):** the large **map panel** shows the **parent → child graph** (Pyvis).
Beside or below: **comment rows** with ``parentCommentId`` / ``commentId`` / ``level`` (same relations in table form).

Run::

  streamlit run final_video_ids_visualization.py
"""

from __future__ import annotations

import csv
import io
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
import streamlit.components.v1 as components

from youtube_ingest_stage1_comments import VIDEO_URLS, extract_video_id
from youtube_streamlit_reply_network import build_reply_network_html, thread_leaderboard
from youtube_streamlit_theme import youtube_theme_css

CURATED_VIDS = [extract_video_id(u) for u in VIDEO_URLS]

# --- Known artifact paths (under ``youtube_out/``) ---
P_STAGE1_META = Path("Youtube_out stage1") / "out_videos_flat.csv"
P_STAGE1_COMMENTS_JSONL = Path("out_video_comments.jsonl")
P_STAGE1_COVERAGE = Path("out_coverage_summary.csv")
P_CT_COMMENTS_JSON = Path("comments and transcripts") / "out_video_comments.json"
P_CT_COVERAGE = Path("comments and transcripts") / "out_coverage_summary.csv"
P_CT_TRANSCRIPTS_JSON = Path("comments and transcripts") / "out_video_transcripts.json"
P_CT_TRANSCRIPT_COV = Path("comments and transcripts") / "out_transcript_coverage_summary.csv"
P_R2_JSON = Path("Comments round two") / "out_video_comments_round_two.json"
P_R2_COVERAGE = Path("Comments round two") / "out_coverage_summary.csv"
P_R3_JSONL = Path("Comments three round") / "out_video_comments_round_three.jsonl"
P_R3_COVERAGE = Path("Comments three round") / "out_coverage_summary_round_three.csv"


def _read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _load_json_array(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _count_by_video(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """Per videoId: top, reply, total row counts."""
    out: Dict[str, Dict[str, int]] = {}
    for r in rows:
        vid = str(r.get("videoId") or "")
        if not vid:
            continue
        if vid not in out:
            out[vid] = {"top": 0, "reply": 0, "total": 0}
        out[vid]["total"] += 1
        if r.get("level") == "reply":
            out[vid]["reply"] += 1
        else:
            out[vid]["top"] += 1
    return out


def _coverage_map(rows: List[Dict[str, str]], vid_key: str = "videoId") -> Dict[str, Dict[str, str]]:
    return {r.get(vid_key, ""): r for r in rows if r.get(vid_key)}


@st.cache_data(show_spinner=False)
def load_summary_bundle(youtube_out: str) -> Dict[str, Any]:
    """Step 1 — fast: CSV + comment JSONL counts only (no full transcript bodies)."""
    root = Path(youtube_out).expanduser().resolve()
    bundle: Dict[str, Any] = {"root": str(root), "paths": {}}

    def p(rel: Path) -> Path:
        return root / rel

    for label, rel in [
        ("stage1_meta", P_STAGE1_META),
        ("stage1_comments_jsonl", P_STAGE1_COMMENTS_JSONL),
        ("stage1_coverage", P_STAGE1_COVERAGE),
        ("r2_json", P_R2_JSON),
        ("r2_coverage", P_R2_COVERAGE),
        ("r3_jsonl", P_R3_JSONL),
        ("r3_coverage", P_R3_COVERAGE),
        ("transcripts_json", P_CT_TRANSCRIPTS_JSON),
        ("transcript_coverage", P_CT_TRANSCRIPT_COV),
    ]:
        fp = p(rel)
        bundle["paths"][label] = {"path": str(fp), "exists": fp.is_file()}

    meta_rows = _read_csv_rows(p(P_STAGE1_META))
    meta_by_vid = {r["videoId"]: r for r in meta_rows if r.get("videoId")}

    s1_rows = _load_jsonl(p(P_STAGE1_COMMENTS_JSONL))
    if not s1_rows:
        s1_rows = _load_json_array(p(P_CT_COMMENTS_JSON))
    s1_counts = _count_by_video(s1_rows)

    r2_rows = _load_json_array(p(P_R2_JSON))
    r2_counts = _count_by_video(r2_rows)

    r3_rows = _load_jsonl(p(P_R3_JSONL))
    r3_counts = _count_by_video(r3_rows)

    s1_ids = {str(r["commentId"]) for r in s1_rows if r.get("commentId")}
    r3_ids = {str(r["commentId"]) for r in r3_rows if r.get("commentId")}
    r2_ids = {str(r["commentId"]) for r in r2_rows if r.get("commentId")}
    cumulative_ids = s1_ids | r3_ids | r2_ids

    cum_counts = _count_by_video(_merge_unique_rows(s1_rows, r2_rows, r3_rows))

    cov_s1 = _coverage_map(_read_csv_rows(p(P_STAGE1_COVERAGE)))
    cov_r2 = _coverage_map(_read_csv_rows(p(P_R2_COVERAGE)))
    cov_r3 = _coverage_map(_read_csv_rows(p(P_R3_COVERAGE)))

    tr_cov = _coverage_map(_read_csv_rows(p(P_CT_TRANSCRIPT_COV)))

    per_video: List[Dict[str, Any]] = []
    for vid in CURATED_VIDS:
        m = meta_by_vid.get(vid, {})
        s1 = s1_counts.get(vid, {"top": 0, "reply": 0, "total": 0})
        r2 = r2_counts.get(vid, {"top": 0, "reply": 0, "total": 0})
        r3 = r3_counts.get(vid, {"top": 0, "reply": 0, "total": 0})
        cum = cum_counts.get(vid, {"top": 0, "reply": 0, "total": 0})
        api_cc = m.get("commentCount", "")
        try:
            api_cc_i = int(api_cc) if api_cc not in ("", None) else None
        except (TypeError, ValueError):
            api_cc_i = None
        gap = (api_cc_i - cum["total"]) if api_cc_i is not None else None

        tr_meta = tr_cov.get(vid, {})

        per_video.append(
            {
                "videoId": vid,
                "title": (m.get("title") or "")[:70],
                "channelTitle": m.get("channelTitle", ""),
                "viewCount": m.get("viewCount", ""),
                "likeCount": m.get("likeCount", ""),
                "api_commentCount": api_cc,
                "s1_top": s1["top"],
                "s1_replies": s1["reply"],
                "s1_total_rows": s1["total"],
                "r2_new_top": r2["top"],
                "r2_new_replies": r2["reply"],
                "r2_new_total": r2["total"],
                "r2_notes": cov_r2.get(vid, {}).get("notes", ""),
                "r3_new_top": r3["top"],
                "r3_new_replies": r3["reply"],
                "r3_new_total": r3["total"],
                "r3_notes": cov_r3.get(vid, {}).get("notes", ""),
                "cumulative_top": cum["top"],
                "cumulative_replies": cum["reply"],
                "cumulative_total_rows": cum["total"],
                "gap_api_minus_cumulative": gap,
                "transcript_status": tr_meta.get("transcript_status", "missing"),
                "transcript_language": tr_meta.get("transcript_language", ""),
            }
        )

    bundle.update(
        {
            "per_video": per_video,
            "totals": {
                "s1_rows": len(s1_rows),
                "r2_rows": len(r2_rows),
                "r3_rows": len(r3_rows),
                "cumulative_unique_ids": len(cumulative_ids),
                "transcripts_ok": sum(
                    1 for r in tr_cov.values() if r.get("transcript_status") == "ok"
                ),
            },
        }
    )
    return bundle


def _merge_unique_rows(
    s1_rows: List[Dict[str, Any]],
    r2_rows: List[Dict[str, Any]],
    r3_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for src in (s1_rows, r2_rows, r3_rows):
        for r in src:
            cid = r.get("commentId")
            if not cid:
                continue
            sc = str(cid)
            if sc in seen:
                continue
            seen.add(sc)
            out.append(r)
    return out


@st.cache_data(show_spinner="Loading cumulative comments…")
def load_cumulative_rows(youtube_out: str) -> List[Dict[str, Any]]:
    """Step 3 — merge stage 1 + round 2 + round 3 comment rows (for network)."""
    root = Path(youtube_out).expanduser().resolve()
    s1 = _load_jsonl(root / P_STAGE1_COMMENTS_JSONL)
    if not s1:
        s1 = _load_json_array(root / P_CT_COMMENTS_JSON)
    r2 = _load_json_array(root / P_R2_JSON)
    r3 = _load_jsonl(root / P_R3_JSONL)
    return _merge_unique_rows(s1, r2, r3)


@st.cache_data(show_spinner="Loading transcripts…")
def load_transcripts(youtube_out: str) -> List[Dict[str, Any]]:
    """Step 2 — full transcript JSON (load only when you open that tab)."""
    return _load_json_array(Path(youtube_out).expanduser().resolve() / P_CT_TRANSCRIPTS_JSON)


def _page_css() -> None:
    st.markdown(youtube_theme_css(), unsafe_allow_html=True)
    st.markdown('<div class="yt-brand-bar"></div>', unsafe_allow_html=True)


def _metric_card(label: str, value: str, sub: str) -> None:
    st.markdown(
        f"""
        <div class="yt-metric-card">
          <div class="yt-metric-label">{label}</div>
          <div class="yt-metric-value">{value}</div>
          <div class="yt-metric-sub">{sub}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _per_video_to_csv(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def _filter_per_video(
    rows: List[Dict[str, Any]],
    *,
    search: str,
    video_id: str,
    gap_filter: str,
) -> List[Dict[str, Any]]:
    out = list(rows)
    if video_id and video_id != "All videos":
        out = [r for r in out if r.get("videoId") == video_id]
    q = search.strip().lower()
    if q:
        out = [
            r
            for r in out
            if q in str(r.get("videoId", "")).lower()
            or q in str(r.get("title", "")).lower()
            or q in str(r.get("channelTitle", "")).lower()
        ]
    if gap_filter == "Has gap vs YouTube":
        out = [r for r in out if r.get("gap_api_minus_cumulative") not in (None, 0, "0")]
    elif gap_filter == "Matches YouTube (±0)":
        out = [r for r in out if r.get("gap_api_minus_cumulative") in (None, 0, "0")]
    return out


_COMMENT_COLS = [
    "publishedAt",
    "level",
    "likeCount",
    "authorDisplayName",
    "commentId",
    "parentCommentId",
    "textDisplay",
]


def _plain_comment_text(raw: Any) -> str:
    if raw is None:
        return ""
    s = str(raw)
    s = re.sub(r"<[^>]+>", " ", s)
    return " ".join(s.split())


def _rows_parent_child_sorted(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group each top-level comment with its direct replies (parent → child order)."""
    children: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    tops: List[Dict[str, Any]] = []

    def _ts(r: Dict[str, Any]) -> str:
        return str(r.get("publishedAt") or "")

    for r in rows:
        if r.get("level") == "reply" and r.get("parentCommentId"):
            children[str(r["parentCommentId"])].append(r)
        else:
            tops.append(r)

    tops.sort(key=_ts, reverse=True)
    out: List[Dict[str, Any]] = []
    placed: set[str] = set()

    def _emit(root: Dict[str, Any]) -> None:
        cid = str(root.get("commentId") or root.get("threadId") or "")
        if cid and cid in placed:
            return
        if cid:
            placed.add(cid)
        out.append(root)
        for kid in sorted(children.get(cid, []), key=_ts, reverse=True):
            kcid = str(kid.get("commentId") or "")
            if kcid and kcid in placed:
                continue
            if kcid:
                placed.add(kcid)
            out.append(kid)

    for t in tops:
        _emit(t)

    for r in rows:
        cid = str(r.get("commentId") or "")
        if cid and cid not in placed:
            out.append(r)
            placed.add(cid)
    return out


def _slim_comment_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    slim: List[Dict[str, Any]] = []
    for r in rows:
        slim.append(
            {
                k: (
                    _plain_comment_text(r.get(k))
                    if k == "textDisplay"
                    else (r.get(k) if k != "parentCommentId" else (r.get(k) or ""))
                )
                for k in _COMMENT_COLS
            }
        )
    return slim


def _render_comments_parent_child_panel(
    rows: List[Dict[str, Any]],
    *,
    key_prefix: str,
    table_height: int = 420,
) -> None:
    """Tabular parent → child view (``parentCommentId`` links reply to parent)."""
    st.markdown('<p class="yt-section-label">Comments</p>', unsafe_allow_html=True)
    if not rows:
        st.warning("No comment rows loaded from cumulative files.")
        return

    vids = sorted({str(r.get("videoId") or "") for r in rows if r.get("videoId")})
    c1, c2, c3 = st.columns([1.1, 1.2, 1])
    with c1:
        scope = st.radio(
            "Rows",
            ["One video", "All 10 videos"],
            horizontal=True,
            key=f"{key_prefix}_cmt_scope",
        )
    with c2:
        if scope == "One video" and vids:
            pick = st.selectbox(
                "Video",
                vids,
                key=f"{key_prefix}_cmt_vid",
            )
            scoped = [r for r in rows if r.get("videoId") == pick]
        else:
            pick = "all"
            scoped = list(rows)
    with c3:
        level_filter = st.selectbox(
            "Level",
            ["All", "Top only", "Replies only"],
            key=f"{key_prefix}_cmt_level",
        )

    if level_filter == "Top only":
        scoped = [
            r
            for r in scoped
            if r.get("level") == "top" or not r.get("parentCommentId")
        ]
    elif level_filter == "Replies only":
        scoped = [r for r in scoped if r.get("level") == "reply"]

    sort_mode = st.radio(
        "Row order",
        ["Thread order (parent, then replies)", "Published (newest first)"],
        horizontal=True,
        key=f"{key_prefix}_cmt_sort",
    )
    if sort_mode.startswith("Thread"):
        display_rows = _rows_parent_child_sorted(scoped)
    else:
        display_rows = sorted(
            scoped, key=lambda r: str(r.get("publishedAt") or ""), reverse=True
        )

    n_top = sum(1 for r in scoped if r.get("level") == "top" or not r.get("parentCommentId"))
    n_rep = sum(1 for r in scoped if r.get("level") == "reply")
    st.caption(
        f"**{pick if scope == 'One video' else 'all videos'}** — "
        f"**{n_top:,}** top · **{n_rep:,}** replies · **{len(display_rows):,}** rows shown"
    )

    slim = _slim_comment_rows(display_rows)
    if slim:
        st.dataframe(slim, use_container_width=True, hide_index=True, height=table_height)
    else:
        st.caption("Nothing to show for this filter.")


def _render_reply_network_panel(
    root: Path,
    *,
    panel_height: int = 640,
    default_scope: str = "All 10 videos",
) -> None:
    """Live parent→child graph in the algae map panel (cumulative rows)."""
    st.markdown('<p class="yt-section-label">Graph</p>', unsafe_allow_html=True)
    with st.container(border=True):
        cum_rows = load_cumulative_rows(str(root))
        scope = st.radio(
            "Scope",
            ["One video", "All 10 videos"],
            index=0 if default_scope.startswith("One") else 1,
            horizontal=True,
            key="map_net_scope",
        )
        if scope == "One video":
            vid = st.selectbox("Video", CURATED_VIDS, key="map_net_vid")
            net_rows = [r for r in cum_rows if r.get("videoId") == vid]
        else:
            net_rows = cum_rows
        enc1, enc2, enc3 = st.columns(3)
        with enc1:
            color_label = st.selectbox(
                "Color nodes by",
                [
                    "Level (thread vs reply)",
                    "Topic (text buckets)",
                    "Video ID (palette)",
                    "Reply reach (thread size)",
                ],
                key="map_net_color",
            )
        with enc2:
            size_label = st.selectbox(
                "Node size",
                ["Uniform", "Engagement (replies + likes)"],
                key="map_net_size",
            )
        with enc3:
            edge_label = st.selectbox(
                "Edge width",
                ["Uniform", "By reply likes"],
                key="map_net_edge",
            )
        _cm = {
            "Level (thread vs reply)": "level",
            "Topic (text buckets)": "topic",
            "Video ID (palette)": "video",
            "Reply reach (thread size)": "reach",
        }
        layout = st.radio(
            "Gephi-style layout",
            [
                "1 — Hierarchical (threads top → bottom)",
                "2 — Force-directed (whole graph, drag & zoom)",
            ],
            horizontal=True,
            key="map_net_layout",
        )
        mode = "hierarchical" if str(layout).startswith("1") else "force"
        st.caption(
            "**1 — Hierarchical** — directed tree (roots at top, replies below), physics off. "
            "**2 — Force** — Barnes–Hut physics on the **whole** network; drag nodes and zoom."
        )

        with st.expander("Thread ranking", expanded=False, key="map_net_thread_rank"):
            st.caption(
                "Gephi **Data Laboratory** preview: thread roots ranked by direct replies in this scope."
            )
            lb = thread_leaderboard(net_rows, limit=25)
            if lb:
                st.dataframe(lb, use_container_width=True, hide_index=True, height=280)
            else:
                st.caption("No reply rows with `parentCommentId` in this scope.")

        canvas_px = max(520, panel_height - 72)
        st.markdown(
            '<p class="yt-section-label" style="margin-top:0.75rem">Network visualization</p>',
            unsafe_allow_html=True,
        )
        if not _pyvis_available():
            st.error(
                "Interactive network needs **pyvis** in this Python environment.\n\n"
                f"**Interpreter:** `{sys.executable}`\n\n"
                "1. Stop Streamlit (Ctrl+C in the terminal).\n"
                "2. Double-click `run_streamlit_final_video_ids.bat` in the WORK folder "
                "(creates `.venv` and installs pyvis).\n"
                "3. Or click **Install graph libraries** in the sidebar, then **Reload**."
            )
            st.markdown(
                f'<div class="yt-network-canvas-slot yt-network-canvas-slot--empty" '
                f'style="min-height:{canvas_px}px" aria-hidden="true"></div>',
                unsafe_allow_html=True,
            )
        else:
            html_doc, note = build_reply_network_html(
                net_rows,
                mode,
                color_mode=_cm[color_label],
                size_mode="engagement" if "Engagement" in size_label else "uniform",
                edge_weight="likes" if "likes" in edge_label else "uniform",
                network_height_px=canvas_px,
            )
            if note:
                st.info(note)
            if html_doc:
                components.html(html_doc, height=panel_height, scrolling=True)
            else:
                st.markdown(
                    f'<div class="yt-network-canvas-slot yt-network-canvas-slot--empty" '
                    f'style="min-height:{canvas_px}px" aria-hidden="true"></div>',
                    unsafe_allow_html=True,
                )
                if not note:
                    st.caption("No edges to draw for this scope.")


_PYVIS_PACKAGES = ("pyvis>=0.3.2", "networkx>=3.0", "jinja2>=3.1.0", "jsonpickle>=3.0.0")


def _pyvis_available() -> bool:
    try:
        from pyvis.network import Network  # noqa: F401

        return True
    except ImportError:
        return False


def _install_pyvis_deps() -> Tuple[bool, str]:
    """Install pyvis and vis.js deps into the same interpreter Streamlit uses."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", *_PYVIS_PACKAGES],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        tail = (proc.stderr or proc.stdout or "").strip()
        if len(tail) > 400:
            tail = "…\n" + tail[-400:]
        return _pyvis_available(), tail
    except Exception as err:
        return False, str(err)


def _fmt_transcript_ts(sec: Any) -> str:
    try:
        t = max(0.0, float(sec))
    except (TypeError, ValueError):
        return "?"
    m = int(t // 60)
    s = t - m * 60
    if m:
        return f"{m}:{s:05.2f}"
    return f"{s:.2f}s"


def _youtube_watch_url(video_id: str, start_sec: float) -> str:
    start = max(0, int(float(start_sec or 0)))
    return f"https://www.youtube.com/watch?v={video_id}&t={start}s"


_PENDING_VIDEO_SYNC = "_pending_dashboard_video"
_PENDING_RESET_FILTERS = "_pending_reset_filters"


def _queue_dashboard_video_sync(video_id: str) -> None:
    """Queue sync for next rerun (cannot set widget keys after widgets are drawn)."""
    st.session_state[_PENDING_VIDEO_SYNC] = video_id


def _migrate_graph_layout_session() -> None:
    """Map old layout radio labels to Gephi-style options (avoids invalid widget state)."""
    val = st.session_state.get("map_net_layout")
    if not val or str(val).startswith(("1", "2")):
        return
    if str(val).startswith("Hierarchical"):
        st.session_state["map_net_layout"] = "1 — Hierarchical (threads top → bottom)"
    else:
        st.session_state["map_net_layout"] = "2 — Force-directed (whole graph, drag & zoom)"


def _apply_session_patches_before_widgets() -> None:
    """Apply queued filter/graph/comment sync before any widgets with those keys exist."""
    _migrate_graph_layout_session()
    if st.session_state.pop(_PENDING_RESET_FILTERS, False):
        st.session_state["yt_search"] = ""
        st.session_state["yt_video"] = "All videos"
        st.session_state["yt_gap"] = "All"

    vid = st.session_state.pop(_PENDING_VIDEO_SYNC, None)
    if not vid:
        return
    st.session_state["yt_video"] = vid
    st.session_state["map_net_scope"] = "One video"
    st.session_state["map_net_vid"] = vid
    st.session_state["main_cmt_scope"] = "One video"
    st.session_state["main_cmt_vid"] = vid
    st.session_state["main_tr_vid"] = vid
    st.session_state["main_tr_last_vid"] = vid


def _transcript_seg_selection_index_from_key(seg_df_key: str) -> Optional[int]:
    """Row index from ``st.dataframe`` selection state (Streamlit ≥ 1.35)."""
    state = st.session_state.get(seg_df_key)
    if not isinstance(state, dict):
        return None
    sel = state.get("selection")
    if not isinstance(sel, dict):
        return None
    rows = sel.get("rows")
    if rows:
        return int(rows[0])
    return None


def _render_transcripts_panel(root: Path, *, key_prefix: str = "tr") -> None:
    """Transcript video + clickable segments synced with YouTube time and dashboard filters."""
    tr_list = load_transcripts(str(root))
    last_vid_key = f"{key_prefix}_last_vid"

    pick = st.selectbox("Video", CURATED_VIDS, key=f"{key_prefix}_vid")
    if st.session_state.get(last_vid_key) != pick:
        st.session_state[last_vid_key] = pick
        _queue_dashboard_video_sync(pick)
        st.rerun()

    # Widget keys include video id so Streamlit does not reuse the first video's state.
    vid_tag = pick
    body_key = f"{key_prefix}_body_{vid_tag}"
    seg_df_key = f"{key_prefix}_seg_df_{vid_tag}"
    jump_key = f"{key_prefix}_jump_{vid_tag}"
    all_key = f"{key_prefix}_all_{vid_tag}"
    n_key = f"{key_prefix}_n_{vid_tag}"

    tr = next((x for x in tr_list if str(x.get("videoId")) == pick), None)
    if not tr:
        st.warning("No transcript for this video in `out_video_transcripts.json`.")
        return

    segs = [s for s in (tr.get("segments") or []) if isinstance(s, dict)]
    if not segs:
        st.caption("No segments stored for this video.")
        return

    n = len(segs)
    st.caption(
        f"**Video `{pick}`** · **status:** {tr.get('status')} · **language:** {tr.get('language')} · "
        f"**{n}** segments · synced with **Filters**, **Comments**, and **Graph**"
    )

    show_all = st.checkbox("Show full transcript", value=True, key=all_key)
    if show_all:
        visible = segs
    else:
        show_n = st.slider(
            "Lines to show",
            min_value=min(20, n),
            max_value=n,
            value=min(30, n),
            key=n_key,
        )
        visible = segs[:show_n]

    table_rows: List[Dict[str, Any]] = []
    for i, s in enumerate(visible):
        start = float(s.get("start") or 0)
        text = _plain_comment_text(s.get("text", ""))
        table_rows.append(
            {
                "Line": i + 1,
                "Time": _fmt_transcript_ts(start),
                "Start (s)": round(start, 3),
                "Text": text,
            }
        )

    if jump_key not in st.session_state:
        st.session_state[jump_key] = 0

    st.markdown(
        '<p class="yt-section-label">Segments — click a row to sync</p>',
        unsafe_allow_html=True,
    )
    seg_event = st.dataframe(
        table_rows,
        use_container_width=True,
        hide_index=True,
        height=min(320, 80 + 28 * len(table_rows)),
        on_select="rerun",
        selection_mode="single-row",
        key=seg_df_key,
    )

    sel_from_df: Optional[int] = None
    if seg_event is not None and getattr(seg_event, "selection", None):
        rows = getattr(seg_event.selection, "rows", None) or []
        if rows:
            sel_from_df = int(rows[0])
    if sel_from_df is None:
        sel_from_df = _transcript_seg_selection_index_from_key(seg_df_key)
    if sel_from_df is not None:
        st.session_state[jump_key] = min(max(0, sel_from_df), len(visible) - 1)

    jump_labels = [
        f"{r['Time']} — {(r['Text'][:70] + '…') if len(r['Text']) > 70 else r['Text']}"
        for r in table_rows
    ]
    jump_i = st.selectbox(
        "Jump to segment",
        range(len(table_rows)),
        format_func=lambda j: jump_labels[j] if jump_labels else str(j),
        key=jump_key,
    )
    active_i = min(max(0, jump_i), len(visible) - 1)
    active = visible[active_i]
    start_sec = float(active.get("start") or 0)
    active_text = _plain_comment_text(active.get("text", ""))

    st.markdown('<p class="yt-section-label">Selected segment</p>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(f"**{_fmt_transcript_ts(start_sec)}** ({start_sec:.3f}s)")
        st.write(active_text)
        c1, c2 = st.columns(2)
        with c1:
            st.link_button(
                "Open on YouTube at this time",
                _youtube_watch_url(pick, start_sec),
                use_container_width=True,
            )
        with c2:
            st.link_button(
                "Open video from start",
                _youtube_watch_url(pick, 0),
                use_container_width=True,
            )

    st.markdown('<p class="yt-section-label">Preview</p>', unsafe_allow_html=True)
    components.iframe(
        f"https://www.youtube.com/embed/{pick}?start={int(start_sec)}&rel=0&sync={vid_tag}_{active_i}",
        height=220,
        scrolling=False,
    )

    lines = []
    for i, s in enumerate(visible):
        mark = "► " if i == active_i else "   "
        lines.append(
            f"{mark}[{_fmt_transcript_ts(s.get('start'))}] {_plain_comment_text(s.get('text', ''))}"
        )
    st.text_area(
        f"Full transcript — {pick} (► = selected segment)",
        "\n".join(lines),
        height=280 if show_all else 200,
        key=body_key,
    )


def main() -> None:
    st.set_page_config(
        page_title="YouTube ingest dashboard",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _page_css()

    cwd = Path(".").resolve()
    default_out = cwd / "youtube_out"
    if not default_out.is_dir():
        default_out = cwd

    with st.sidebar:
        st.markdown("##### Settings")
        st.caption(f"Python: `{sys.executable}`")
        raw = st.text_input("Data folder (`youtube_out`)", value=str(default_out))
        if not _pyvis_available():
            st.warning("Graph libraries not loaded in this Python.")
            if st.button("Install graph libraries", use_container_width=True):
                with st.spinner("Installing pyvis, networkx, jinja2…"):
                    ok, log = _install_pyvis_deps()
                if ok:
                    st.success("Installed. Reloading…")
                    st.rerun()
                else:
                    st.error(f"Install failed. Try `run_streamlit_final_video_ids.bat`.\n\n{log}")
        else:
            st.caption("Graph libraries: **ready**")
        preview_path = Path(__file__).resolve().parent / "youtube_out" / "network_preview.html"
        if preview_path.is_file():
            st.link_button(
                "Open saved graph preview (browser)",
                f"file:///{preview_path.as_posix()}",
                use_container_width=True,
            )
        if st.button("Reload from disk", use_container_width=True):
            st.cache_data.clear()
            for k in list(st.session_state.keys()):
                if k.startswith(("yt_", "main_", "map_", "main_tr", "tr_")):
                    st.session_state.pop(k, None)
            st.rerun()

    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        st.error(f"Not a directory: `{root}`")
        st.stop()

    try:
        bundle = load_summary_bundle(str(root))
    except Exception as err:
        st.exception(err)
        st.stop()

    t = bundle["totals"]
    pv_all: List[Dict[str, Any]] = bundle["per_video"]
    csv_all = _per_video_to_csv(pv_all)

    h_left, h_right = st.columns([2.2, 1])
    with h_left:
        st.markdown(
            """
            <div class="yt-dash-header">
              <p class="yt-dash-title">YouTube curated videos dashboard</p>
              <p class="yt-dash-subtitle">Stage 1 · Round 2 · Round 3 — file-backed counts for 10 video IDs (no live API calls)</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with h_right:
        b1, b2 = st.columns(2)
        with b1:
            if st.button("Reset filters", use_container_width=True):
                st.session_state[_PENDING_RESET_FILTERS] = True
                st.rerun()
        with b2:
            st.download_button(
                "Export",
                data=csv_all,
                file_name="youtube_ingest_summary.csv",
                mime="text/csv",
                use_container_width=True,
                disabled=not csv_all,
            )

    _apply_session_patches_before_widgets()

    # --- Metric cards ---
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        _metric_card("Stage 1 rows", f"{t['s1_rows']:,}", "comment + reply rows")
    with m2:
        _metric_card("Round 2 new", f"{t['r2_rows']:,}", "incremental ingest")
    with m3:
        _metric_card("Round 3 new", f"{t['r3_rows']:,}", "deeper pass only")
    with m4:
        _metric_card("Cumulative", f"{t['cumulative_unique_ids']:,}", "unique commentIds")
    with m5:
        _metric_card(
            "Transcripts",
            f"{t['transcripts_ok']}/{len(CURATED_VIDS)}",
            "status ok in coverage CSV",
        )

    st.markdown('<p class="yt-filter-heading">Filters</p>', unsafe_allow_html=True)
    with st.container(border=True):
        f1, f2, f3 = st.columns([2, 1.2, 1])
        with f1:
            search = st.text_input(
                "Search",
                placeholder="Search video id, title, channel…",
                key="yt_search",
            )
        with f2:
            video_pick = st.selectbox(
                "Video",
                ["All videos"] + CURATED_VIDS,
                key="yt_video",
                format_func=lambda v: v if v == "All videos" else f"{v}",
            )
            if video_pick != "All videos":
                last_f = st.session_state.get("_last_filter_video")
                if last_f != video_pick:
                    st.session_state["_last_filter_video"] = video_pick
                    st.session_state["main_tr_vid"] = video_pick
                    st.session_state["main_tr_last_vid"] = video_pick
        with f3:
            gap_filter = st.selectbox(
                "Coverage vs YouTube",
                ["All", "Has gap vs YouTube", "Matches YouTube (±0)"],
                key="yt_gap",
            )

    pv_filtered = _filter_per_video(
        pv_all, search=search, video_id=video_pick, gap_filter=gap_filter
    )
    st.caption(f"**{len(pv_filtered)}** of **{len(pv_all)}** videos")

    graph_h = 880
    table_h = 520
    cum_rows = load_cumulative_rows(str(root))

    col_comments, col_graph = st.columns([1, 2.2], gap="large")
    with col_graph:
        _render_reply_network_panel(
            root, panel_height=graph_h, default_scope="One video"
        )
    with col_comments:
        _render_comments_parent_child_panel(
            cum_rows, key_prefix="main", table_height=table_h
        )
        with st.expander("Transcripts", expanded=False):
            _render_transcripts_panel(root, key_prefix="main_tr")
        with st.expander("Coverage summary", expanded=False):
            st.dataframe(pv_filtered, use_container_width=True, hide_index=True, height=200)
            st.download_button(
                "Export summary CSV",
                data=_per_video_to_csv(pv_filtered),
                file_name="youtube_ingest_summary.csv",
                mime="text/csv",
                disabled=not pv_filtered,
            )


if __name__ == "__main__":
    main()
