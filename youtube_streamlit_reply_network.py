"""
Reply graph for the dashboard. Each arrow goes from parentCommentId to the reply.
"""

from __future__ import annotations

import hashlib
import math
import re
from html import unescape
from typing import Any, Dict, List, Tuple

from youtube_streamlit_theme import (
    YT_EDGE_COLOR,
    YT_EDGE_HIGHLIGHT,
    YT_EDGE_HOVER,
    YT_GRAPH_CANVAS,
    YT_GRAPH_CANVAS_NET,
    YT_NODE_REPLY_BORDER,
    YT_NODE_REPLY_FILL,
    YT_NODE_TOP_BORDER,
    YT_NODE_TOP_FILL,
    YT_NODE_TOP_LABEL,
    YT_TEXT,
    YT_TEXT_SECONDARY,
    YT_TOPIC_PALETTE,
)

# Node color, size, and edge width for the reply graph.

_TOPIC_PALETTE: Dict[str, Tuple[str, str]] = dict(YT_TOPIC_PALETTE)

# Distinct hues for multi-video graphs (fill, border).
_VIDEO_SWATCHES: List[Tuple[str, str]] = [
    ("#ede9fe", "#5b21b6"),
    ("#cffafe", "#0e7490"),
    ("#dcfce7", "#15803d"),
    ("#fef3c7", "#b45309"),
    ("#fce7f3", "#be185d"),
    ("#fee2e2", "#b91c1c"),
    ("#e0e7ff", "#4338ca"),
    ("#ccfbf1", "#0f766e"),
    ("#ffedd5", "#c2410c"),
    ("#f3e8ff", "#7c3aed"),
    ("#dbeafe", "#1d4ed8"),
    ("#ecfccb", "#4d7c0f"),
    ("#fff1f2", "#9f1239"),
    ("#fef9c3", "#a16207"),
]

# Thread reply volume: cool (quiet) → warm (busy); node fill stays light for labels
_REACH_NODE_PAIRS: List[Tuple[str, str]] = [
    ("#eef2ff", "#4338ca"),
    ("#e0f2fe", "#0369a1"),
    ("#ccfbf1", "#0f766e"),
    ("#ecfccb", "#4d7c0f"),
    ("#fef9c3", "#ca8a04"),
    ("#ffedd5", "#ea580c"),
    ("#fee2e2", "#b91c1c"),
]

# CSS linear-gradient for legend bar (approximates node ramp)
_REACH_LEGEND_GRADIENT = (
    "linear-gradient(90deg, #eef2ff 0%, #e0f2fe 16%, #ccfbf1 33%, "
    "#ecfccb 50%, #fef9c3 66%, #ffedd5 83%, #fee2e2 100%)"
)

# Edge colour by reply likes (cool → saturated indigo/violet)
_EDGE_LIKE_COLORS: List[str] = [
    "#d0d0d0",
    "#a8a8a8",
    "#808080",
    "#cc0000",
    "#8a0000",
]

_EDGE_LEGEND_GRADIENT = (
    "linear-gradient(90deg, #e5e5e5 0%, #a8a8a8 35%, #cc0000 70%, #8a0000 100%)"
)
_VIDEO_LEGEND_GRADIENT = (
    "linear-gradient(90deg, #5b21b6 0%, #0e7490 18%, #15803d 36%, "
    "#b45309 54%, #be185d 72%, #4338ca 100%)"
)


def _topic_bucket(text_plain: str) -> str:
    """
   critical-thinking style threads.
    """
    t = text_plain.lower()
    if any(
        w in t
        for w in (
            "fallacy",
            "bias",
            "premise",
            "therefore",
            "logic",
            "reasoning",
            "argument",
            "evidence",
            "hypothesis",
            "assumption",
            "infer",
            "valid",
            "sound",
            "counterargument",
        )
    ):
        return "critical"
    if "?" in t or any(p in t for p in ("why ", "how ", "what if", "do you think", "could it be")):
        return "question"
    if len(t) < 140 and any(
        p in t for p in ("lol", "lmao", "haha", "thanks", "thank you", "agree", "disagree", "so true", "facts")
    ):
        return "reaction"
    return "other"


def _video_color_pair(video_id: str) -> Tuple[str, str]:
    h = int(hashlib.md5(video_id.encode("utf-8")).hexdigest(), 16)
    return _VIDEO_SWATCHES[h % len(_VIDEO_SWATCHES)]


def _safe_like(v: Any) -> int:
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return 0


def _reply_counts_by_parent(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rows:
        if r.get("level") != "reply":
            continue
        pid = r.get("parentCommentId")
        if not pid:
            continue
        p = str(pid)
        out[p] = out.get(p, 0) + 1
    return out


def _reach_ratio(count: int, max_count: int) -> float:
    if max_count <= 0:
        return 0.0
    return min(1.0, count / max_count)


def _reach_colors(ratio: float) -> Tuple[str, str]:
    if not _REACH_NODE_PAIRS:
        return "#f1f5f9", "#64748b"
    n = len(_REACH_NODE_PAIRS)
    if n == 1:
        return _REACH_NODE_PAIRS[0]
    x = min(1.0, max(0.0, ratio)) * (n - 1)
    i = int(round(x))
    i = min(max(i, 0), n - 1)
    return _REACH_NODE_PAIRS[i]


def _edge_color_vis(lk: int, max_lk: int, *, color_by_likes: bool) -> Dict[str, str]:
    """vis.js edge ``color`` dict: main line + hover emphasis."""
    if not color_by_likes or max_lk <= 0:
        return {
            "color": YT_EDGE_COLOR,
            "highlight": YT_EDGE_HIGHLIGHT,
            "hover": YT_EDGE_HOVER,
        }
    t = min(1.0, lk / max_lk)
    stops = _EDGE_LIKE_COLORS
    x = t * (len(stops) - 1)
    j = int(round(x))
    j = min(max(j, 0), len(stops) - 1)
    main = stops[j]
    hi = stops[min(len(stops) - 1, j + 1)] if j < len(stops) - 1 else main
    return {"color": main, "highlight": "#1e293b", "hover": hi}


def _legend_scale_block(inner_html: str) -> str:
    return f'<div class="rnet-scale-full" role="group">{inner_html}</div>'


def _legend_continuous_scale(title: str, gradient_css: str, left_label: str, right_label: str) -> str:
    return (
        f'<div class="rnet-scale-block">'
        f'<div class="rnet-scale-title">{title}</div>'
        f'<div class="rnet-scale-bar" style="background:{gradient_css};"></div>'
        f'<div class="rnet-scale-ticks"><span>{left_label}</span><span>{right_label}</span></div>'
        f"</div>"
    )


def _topic_legend_swatches_html() -> str:
    parts = ['<span class="rnet-legend-item"><b>Color = topic (keyword buckets)</b></span>']
    for key in ("critical", "question", "reaction", "other"):
        fill, border = _TOPIC_PALETTE[key]
        parts.append(
            f'<span class="rnet-legend-item"><span class="rnet-swatch" '
            f'style="background:{fill};border:2px solid {border}"></span> {key}</span>'
        )
    return "".join(parts)


def _plain_text(s: str) -> str:
    """YouTube ``textDisplay`` / names often include ``<a>``, ``<br>``; tooltips must be plain text."""
    t = unescape(str(s))
    raw = re.sub(r"<[^>]+>", " ", t)
    return " ".join(raw.split())


def _plain_label(s: str, max_len: int) -> str:
    """Strip simple HTML-ish noise for a tiny on-canvas label."""
    raw = re.sub(r"<[^>]+>", " ", unescape(str(s)))
    raw = " ".join(raw.split())
    if not raw:
        raw = "?"
    if len(raw) <= max_len:
        return raw
    return raw[: max(1, max_len - 1)] + "…"


def _one_line(s: str, max_len: int | None = None) -> str:
    """Collapse whitespace/newlines for tooltip lines (no HTML)."""
    t = " ".join(str(s).split())
    if max_len is not None and len(t) > max_len:
        return t[: max(1, max_len - 1)] + "…"
    return t


def _node_tooltip_plain(
    author: str,
    level: str,
    likes: str,
    pub: str,
    text: str,
    cid: str,
    pid: str,
    is_top: bool,
    text_max: int = 500,
    extra_tail: str = "",
) -> str:
    """Plain-text hover (vis.js shows ``title`` as text, not rendered HTML)."""
    author = _plain_text(author)
    text = _plain_text(text)
    if len(text) <= text_max:
        body = _one_line(text)
    else:
        body = _one_line(text[:text_max]) + "…"
    lines = [
        _one_line(author, 200),
        level,
        f"likes: {likes} · {pub}",
        "",
        body,
        "",
        f"commentId: {cid}",
    ]
    if not is_top and pid:
        lines.insert(-1, f"parentCommentId → this node: {pid}")
    out = "\n".join(lines)
    if extra_tail.strip():
        out += "\n\n" + extra_tail.strip()
    return out


def _edge_tooltip_plain(parent_id: str, reply_id: str, likes_line: str = "") -> str:
    base = (
        "Directed edge (parent → reply)\n"
        f"from (parent): {parent_id}\n"
        f"to (reply): {reply_id}"
    )
    if likes_line:
        return base + "\n" + likes_line
    return base


def _inject_chrome(html: str, legend_extras: str = "") -> str:
    """Add CSS + a compact legend under Streamlit / vis defaults."""
    head_css = f"""
<style>
  html, body {{
    margin: 0;
    padding: 0;
    height: 100%;
    font-family: ui-sans-serif, system-ui, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: {YT_GRAPH_CANVAS};
    -webkit-font-smoothing: antialiased;
  }}
  .rnet-chrome {{
    background: linear-gradient(180deg, #ffffff 0%, #f9f9f9 100%);
    border-bottom: 1px solid #e5e5e5;
    padding: 10px 14px 10px 14px;
    font-size: 12px;
    color: {YT_TEXT_SECONDARY};
    letter-spacing: 0.01em;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 18px 22px;
  }}
  .rnet-chrome b {{ color: {YT_TEXT}; font-weight: 600; }}
  .rnet-legend-item {{ display: inline-flex; align-items: center; gap: 8px; }}
  .rnet-swatch {{
    width: 14px; height: 14px; border-radius: 50%;
    box-shadow: 0 0 0 2px #fff, 0 0 0 3px #d0d0d0;
  }}
  .rnet-scale-full {{
    flex: 1 1 100%;
    width: 100%;
    margin-top: 6px;
    padding-top: 10px;
    border-top: 1px solid #e5e5e5;
  }}
  .rnet-scale-grid {{
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 14px 28px;
    align-items: start;
  }}
  @media (max-width: 720px) {{
    .rnet-scale-grid {{ grid-template-columns: 1fr; }}
  }}
  .rnet-scale-block {{ min-width: 0; }}
  .rnet-scale-title {{
    font-size: 11px;
    font-weight: 600;
    color: {YT_TEXT_SECONDARY};
    margin-bottom: 4px;
    line-height: 1.35;
  }}
  .rnet-scale-bar {{
    height: 14px;
    border-radius: 7px;
    border: 1px solid #d0d0d0;
    box-shadow: inset 0 1px 2px rgba(255,255,255,0.6);
  }}
  .rnet-scale-ticks {{
    display: flex;
    justify-content: space-between;
    font-size: 10px;
    color: #909090;
    margin-top: 3px;
    line-height: 1.2;
  }}
  #mynetwork {{
    border: 1px solid #e5e5e5 !important;
    border-top: none !important;
    border-radius: 0 0 10px 10px !important;
    background: {YT_GRAPH_CANVAS_NET} !important;
    box-sizing: border-box;
  }}
  .vis-network {{
    background-color: {YT_GRAPH_CANVAS_NET} !important;
    outline: none;
  }}
  .vis-tooltip {{
    z-index: 2147483647 !important;
    position: absolute !important;
    max-width: 360px;
    white-space: pre-wrap !important;
    font-family: ui-sans-serif, system-ui, "Segoe UI", Roboto, sans-serif !important;
    border-radius: 8px !important;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.1) !important;
    border: 1px solid #e5e5e5 !important;
  }}
</style>
"""
    legend = f"""
<div class="rnet-chrome" aria-label="Graph legend">
  <span><b>Parent → child</b> &nbsp;·&nbsp; red = thread start · gray dot = reply · <b>arrow points to the reply</b></span>
  <span class="rnet-legend-item"><span class="rnet-swatch" style="background:{YT_NODE_TOP_FILL};border:2px solid {YT_NODE_TOP_BORDER}"></span> Thread (top comment)</span>
  <span class="rnet-legend-item"><span class="rnet-swatch" style="background:{YT_NODE_REPLY_FILL};border:2px solid {YT_NODE_REPLY_BORDER}"></span> Reply (hover for text)</span>
  <span class="rnet-legend-item">↳ directed edge toward reply</span>
"""
    if legend_extras.strip():
        legend += legend_extras + "\n"
    legend += "</div>"
    if "</head>" in html:
        html = html.replace("</head>", head_css + "\n</head>", 1)
    # Insert legend immediately after opening body tag
    html, n = re.subn(r"(<body[^>]*>)", r"\1" + legend, html, count=1)
    if n == 0 and "<body>" in html:
        html = html.replace("<body>", "<body>" + legend, 1)
    return html


def thread_leaderboard(
    video_rows: List[Dict[str, Any]],
    *,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Rank thread starters by reply count and likes."""
    by_id: Dict[str, Dict[str, Any]] = {}
    for r in video_rows:
        cid = r.get("commentId")
        if cid:
            by_id[str(cid)] = r
    counts = _reply_counts_by_parent(video_rows)
    like_sum: Dict[str, int] = {k: 0 for k in counts}
    for r in video_rows:
        if r.get("level") != "reply":
            continue
        pid = r.get("parentCommentId")
        if not pid:
            continue
        p = str(pid)
        if p not in like_sum:
            continue
        like_sum[p] += _safe_like(r.get("likeCount"))
    rows: List[Dict[str, Any]] = []
    for tid, nrep in sorted(counts.items(), key=lambda kv: (-kv[1], -like_sum.get(kv[0], 0))):
        root = by_id.get(tid) or {}
        snippet = _plain_label(str(root.get("textDisplay") or ""), 80)
        rows.append(
            {
                "threadRootId": tid,
                "directRepliesInFile": nrep,
                "replyLikesSum": like_sum.get(tid, 0),
                "rootLikes": _safe_like(root.get("likeCount")),
                "author": _plain_text(str(root.get("authorDisplayName") or ""))[:40],
                "snippet": snippet,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def build_reply_network_html(
    video_rows: List[Dict[str, Any]],
    layout_mode: str,
    top_color: str = YT_NODE_TOP_FILL,
    top_border: str = YT_NODE_TOP_BORDER,
    *,
    color_mode: str = "level",
    size_mode: str = "uniform",
    edge_weight: str = "uniform",
    network_height_px: int = 620,
) -> Tuple[str, str]:
    """
    Directed graph: one edge per reply from **parent** ``parentCommentId`` → **child** ``commentId``.

    **color_mode** (node fill/border):

    - ``level`` — thread root vs reply (default look).
    - ``topic`` — light **text buckets** on ``textDisplay`` (critical / question / reaction / other); not ML labels.
    - ``video`` — one hue per ``videoId`` (useful when ``video_rows`` mixes several videos).
    - ``reach`` — warmer colors for thread roots with **more direct replies** in this file; replies match their parent thread.

    **size_mode**: ``uniform`` | ``engagement`` (reply fan-out on roots; likes on replies).

    **edge_weight**: ``uniform`` | ``likes`` (thicker, **more saturated** edge when the **reply** row has higher ``likeCount``; legend shows a colour scale).
    """
    try:
        from pyvis.network import Network
    except ImportError:
        return (
            "",
            "Install **pyvis** to see the network: `pip install pyvis` (listed in `requirements.txt`).",
        )

    by_id: Dict[str, Dict[str, Any]] = {}
    for r in video_rows:
        cid = r.get("commentId")
        if cid:
            by_id[str(cid)] = r

    if not by_id:
        return "", "No rows with a `commentId` for this video."

    reply_count_by_parent = _reply_counts_by_parent(video_rows)
    max_r = max(reply_count_by_parent.values(), default=0)
    distinct_vids = sorted({str(r.get("videoId") or "") for r in video_rows if r.get("videoId")})
    n_videos = len(distinct_vids)
    row_by_comment_id: Dict[str, Dict[str, Any]] = {
        str(r["commentId"]): r for r in video_rows if r.get("commentId")
    }
    max_edge_likes = 0
    for r in video_rows:
        if r.get("parentCommentId") and r.get("commentId"):
            max_edge_likes = max(max_edge_likes, _safe_like(r.get("likeCount")))

    cm = (color_mode or "level").lower().strip()
    sm = (size_mode or "uniform").lower().strip()
    ew_mode = (edge_weight or "uniform").lower().strip()
    if cm not in ("level", "topic", "video", "reach"):
        cm = "level"
    if sm not in ("uniform", "engagement"):
        sm = "uniform"
    if ew_mode not in ("uniform", "likes"):
        ew_mode = "uniform"

    legend_extras = ""
    scale_inner_parts: List[str] = []

    if cm == "topic":
        legend_extras += _topic_legend_swatches_html()
    elif cm == "video":
        legend_extras += (
            f'<span class="rnet-legend-item"><b>Color = videoId</b> ({n_videos} distinct; stable hash → palette)</span>'
        )
        scale_inner_parts.append(
            _legend_continuous_scale(
                "Video hues (illustrative gradient — each video maps to one swatch family)",
                _VIDEO_LEGEND_GRADIENT,
                "palette start",
                "palette end",
            )
        )
    elif cm == "reach":
        legend_extras += (
            '<span class="rnet-legend-item"><b>Color = reply reach</b> (warmer = more direct replies in this file)</span>'
        )
        scale_inner_parts.append(
            _legend_continuous_scale(
                f"Node colour · direct replies on thread (max in this view: {max_r})"
                if max_r > 0
                else "Node colour · direct replies on thread (no reply rows in view)",
                _REACH_LEGEND_GRADIENT,
                "fewer replies",
                "more replies",
            )
        )
    if sm == "engagement":
        legend_extras += (
            '<span class="rnet-legend-item"><b>Node size</b> scales with reply fan-out (root) / likes (reply)</span>'
        )
    if ew_mode == "likes":
        legend_extras += (
            '<span class="rnet-legend-item"><b>Edges</b> — width + colour scale with reply likeCount</span>'
        )
        scale_inner_parts.append(
            _legend_continuous_scale(
                f"Edge colour & width · reply likes (max in view: {max_edge_likes})"
                if max_edge_likes > 0
                else "Edge colour & width · reply likes (all zero in view)",
                _EDGE_LEGEND_GRADIENT,
                "0 likes",
                "highest likes",
            )
        )

    if scale_inner_parts:
        legend_extras += _legend_scale_block(
            '<div class="rnet-scale-grid">' + "".join(scale_inner_parts) + "</div>"
        )

    if layout_mode == "hierarchical":
        legend_extras += (
            '<span class="rnet-legend-item"><b>Layout</b> 1 — Hierarchical (UD, physics off)</span>'
        )
    else:
        legend_extras += (
            '<span class="rnet-legend-item"><b>Layout</b> 2 — Force-directed (whole graph)</span>'
        )

    canvas_h = max(400, int(network_height_px))
    net = Network(
        height=f"{canvas_h}px",
        width="100%",
        bgcolor=YT_GRAPH_CANVAS_NET,
        font_color=YT_TEXT,
        directed=True,
        cdn_resources="remote",
    )

    reply_fill_default = YT_NODE_REPLY_FILL
    reply_border_default = YT_NODE_REPLY_BORDER

    for cid, r in by_id.items():
        is_top = r.get("level") == "top" or not r.get("parentCommentId")
        author = str(r.get("authorDisplayName") or "?")
        text = str(r.get("textDisplay") or "")
        level = "Top-level thread" if is_top else "Reply"
        pid_raw = r.get("parentCommentId") or ""
        pid = str(pid_raw) if pid_raw else ""
        pub = str(r.get("publishedAt") or "")
        likes = r.get("likeCount", "")
        likes_i = _safe_like(likes)
        plain_body = _plain_text(text)
        bucket = _topic_bucket(plain_body)
        vid = str(r.get("videoId") or "")

        if cm == "level":
            fill = top_color if is_top else reply_fill_default
            border = top_border if is_top else reply_border_default
        elif cm == "topic":
            fill, border = _TOPIC_PALETTE.get(bucket, _TOPIC_PALETTE["other"])
        elif cm == "video":
            fill, border = _video_color_pair(vid) if vid else _TOPIC_PALETTE["other"]
        else:
            n_for_reach = reply_count_by_parent.get(str(cid), 0) if is_top else reply_count_by_parent.get(pid, 0)
            fill, border = _reach_colors(_reach_ratio(n_for_reach, max_r))

        if sm == "engagement":
            if is_top:
                rc = reply_count_by_parent.get(str(cid), 0)
                size = min(52.0, max(22.0, 18.0 + 2.6 * math.sqrt(1 + rc)))
            else:
                size = min(28.0, max(10.0, 10.0 + 1.4 * math.sqrt(1 + likes_i)))
        else:
            size = 30.0 if is_top else 11.0

        extra_lines: List[str] = []
        if vid:
            extra_lines.append(f"videoId: {vid}")
        if cm == "topic":
            extra_lines.append(f"Topic bucket (text heuristics): {bucket}")
        if cm == "reach":
            if is_top:
                extra_lines.append(
                    f"Direct replies in file on this thread: {reply_count_by_parent.get(str(cid), 0)} (max in view: {max_r})"
                )
            elif pid:
                extra_lines.append(
                    f"Thread replies in file (under parent): {reply_count_by_parent.get(pid, 0)}"
                )
        extra_tail = "\n".join(extra_lines)

        tip = _node_tooltip_plain(
            author=author,
            level=level,
            likes=str(likes),
            pub=pub,
            text=text,
            cid=str(cid),
            pid=pid,
            is_top=is_top,
            extra_tail=extra_tail,
        )

        short = _plain_label(author, 14 if is_top else 10)
        canvas_label = f"● {short}" if is_top else ""

        if cm == "level" and is_top:
            fcolor = YT_NODE_TOP_LABEL
            stroke = "#8a0000"
            stroke_w = 2
        elif cm == "level":
            fcolor = YT_TEXT_SECONDARY
            stroke = "#ffffff"
            stroke_w = 0
        else:
            fcolor = YT_TEXT if is_top else YT_TEXT_SECONDARY
            stroke = "#ffffff"
            stroke_w = 1 if is_top else 0

        if cm == "level" and is_top:
            hibg, hibd = "#ff4e45", "#5c0000"
        elif cm == "level":
            hibg, hibd = "#fff5f5", YT_EDGE_HOVER
        else:
            hibg, hibd = "#f5f5f5", "#909090"

        net.add_node(
            cid,
            label=canvas_label,
            title=tip,
            shape="dot",
            size=size,
            color={
                "background": fill,
                "border": border,
                "highlight": {"background": hibg, "border": hibd},
            },
            borderWidth=3 if is_top else 2,
            borderWidthSelected=4 if is_top else 3,
            font={
                "size": 12 if is_top else 1,
                "color": fcolor,
                "face": "Roboto, ui-sans-serif, system-ui, Segoe UI, sans-serif",
                "strokeWidth": stroke_w,
                "strokeColor": stroke,
                "bold": is_top,
                "vadjust": -52 if is_top else 0,
            },
            shadow={
                "enabled": True,
                "color": "rgba(0,0,0,0.12)" if is_top else "rgba(0,0,0,0.06)",
                "size": 8 if is_top else 4,
                "x": 0,
                "y": 2,
            },
        )

    missing_parent = 0
    edges_added = 0
    seen_e: set[Tuple[str, str]] = set()
    for r in video_rows:
        cid = r.get("commentId")
        pid = r.get("parentCommentId")
        if not cid or not pid:
            continue
        sc, sp = str(cid), str(pid)
        if sp not in by_id:
            missing_parent += 1
            continue
        if sc not in by_id:
            continue
        key = (sp, sc)
        if key in seen_e:
            continue
        seen_e.add(key)
        child_row = row_by_comment_id.get(sc, {})
        lk = _safe_like(child_row.get("likeCount"))
        w = 2.0 if ew_mode != "likes" else min(6.0, 1.8 + 0.5 * math.log(1 + lk))
        ecol = _edge_color_vis(lk, max_edge_likes, color_by_likes=(ew_mode == "likes"))
        etip = _edge_tooltip_plain(sp, sc, f"reply likeCount: {lk}" if ew_mode == "likes" else "")
        net.add_edge(
            sp,
            sc,
            title=etip,
            color=ecol,
            width=w,
        )
        edges_added += 1

    edge_smooth = (
        '"smooth": { "type": "cubicBezier", "forceDirection": "vertical", "roundness": 0.45 }'
        if layout_mode == "hierarchical"
        else '"smooth": { "type": "dynamic", "roundness": 0.5 }'
    )

    node_scale_min = 8 if sm == "engagement" else 10
    node_scale_max = 48 if sm == "engagement" else 32

    base_opts = f"""
    "configure": {{ "enabled": false }},
    "manipulation": {{ "enabled": false }},
    "nodes": {{
      "font": {{
        "size": 12,
        "face": "Roboto, ui-sans-serif, system-ui, Segoe UI, sans-serif",
        "color": "{YT_TEXT}"
      }},
      "scaling": {{ "min": {node_scale_min}, "max": {node_scale_max} }}
    }},
    "edges": {{
      "color": {{
        "color": "{YT_EDGE_COLOR}",
        "highlight": "{YT_EDGE_HIGHLIGHT}",
        "hover": "{YT_EDGE_HOVER}",
        "inherit": false
      }},
      "width": 2,
      "arrows": {{
        "to": {{
          "enabled": true,
          "scaleFactor": 1.05,
          "type": "arrow"
        }}
      }},
      "arrowStrikethrough": false,
      "selectionWidth": 3,
      "hoverWidth": 2.8,
      {edge_smooth}
    }},
    "interaction": {{
      "hover": true,
      "hoverConnectedEdges": true,
      "tooltipDelay": 120,
      "navigationButtons": true,
      "keyboard": true,
      "zoomView": true,
      "dragView": true,
      "multiselect": false,
      "hideEdgesOnDrag": false,
      "hideNodesOnDrag": false
    }}
    """

    if layout_mode == "hierarchical":
        net.set_options(
            """
            {
            """
            + base_opts
            + """
              ,
              "layout": {
                "hierarchical": {
                  "enabled": true,
                  "levelSeparation": 200,
                  "nodeSpacing": 160,
                  "treeSpacing": 220,
                  "direction": "UD",
                  "sortMethod": "directed",
                  "shakeTowards": "leaves"
                }
              },
              "physics": { "enabled": false }
            }
            """
        )
    else:
        net.set_options(
            """
            {
            """
            + base_opts
            + """
              ,
              "layout": {
                "improvedLayout": true,
                "clusterThreshold": 200
              },
              "physics": {
                "enabled": true,
                "solver": "barnesHut",
                "barnesHut": {
                  "gravitationalConstant": -24000,
                  "centralGravity": 0.22,
                  "springLength": 180,
                  "springConstant": 0.045,
                  "avoidOverlap": 0.92,
                  "damping": 0.52
                },
                "minVelocity": 0.55,
                "stabilization": {
                  "enabled": true,
                  "iterations": 280,
                  "updateInterval": 20,
                  "fit": true
                }
              }
            }
            """
        )

    notes: List[str] = []
    layout_note = (
        "Layout **hierarchical** (threads top → bottom, no physics)."
        if layout_mode == "hierarchical"
        else "Layout **force-directed** (whole graph; drag nodes, zoom, let physics settle)."
    )
    notes.append(
        f"{layout_note} Red nodes = thread starts. Gray dots = replies (hover for text). "
        f"Arrows point to the reply. Encoding: color **{cm}**, size **{sm}**, edges **{ew_mode}**."
    )
    if edges_added == 0 and len(by_id) > 1:
        notes.append(
            "No **parent -> reply** edges drawn (every row may be top-level, or `parentCommentId` is missing)."
        )
    if missing_parent:
        notes.append(
            f"{missing_parent} reply row(s) point to a **parent** `commentId` that is **not** in this file for this video."
        )
    if len(by_id) > 300:
        notes.append(f"Large graph (**{len(by_id)}** nodes); drag/zoom may feel heavy.")

    html = _inject_chrome(net.generate_html(), legend_extras=legend_extras)
    return html, " ".join(notes)
