"""
Calm YouTube-inspired palette for Streamlit dashboards (comments / ingest UI).

Colors approximate YouTube web UI: warm white surfaces, #0f0f0f text, soft grays,
muted red accent — not neon brand red.
"""

from __future__ import annotations

# --- Core palette ---
YT_BG = "#f9f9f9"
YT_SURFACE = "#ffffff"
YT_SIDEBAR = "#f8f8f8"
YT_TEXT = "#0f0f0f"
YT_TEXT_SECONDARY = "#606060"
YT_TEXT_MUTED = "#909090"
YT_BORDER = "#e5e5e5"
YT_BORDER_STRONG = "#d0d0d0"
YT_ACCENT = "#cc0000"
YT_ACCENT_SOFT = "#fff5f5"
YT_ACCENT_MID = "#ff4e45"
YT_LINK = "#065fd4"
YT_GRAPH_CANVAS = "#fafafa"
YT_GRAPH_EMPTY = "#f1f1f1"

# Network graph (level mode) — high contrast: red thread roots, white replies
YT_NODE_TOP_FILL = "#cc0000"
YT_NODE_TOP_BORDER = "#8a0000"
YT_NODE_REPLY_FILL = "#ffffff"
YT_NODE_REPLY_BORDER = "#606060"
YT_NODE_TOP_LABEL = "#ffffff"
YT_NODE_REPLY_LABEL = "#0f0f0f"
YT_EDGE_COLOR = "#4a4a4a"
YT_EDGE_HOVER = "#cc0000"
YT_EDGE_HIGHLIGHT = "#0f0f0f"
YT_GRAPH_CANVAS_NET = "#ffffff"

# Topic buckets — calmer, still distinct
YT_TOPIC_PALETTE: dict[str, tuple[str, str]] = {
    "critical": ("#fff5f5", "#b91c1c"),
    "question": ("#f0f7ff", "#1a5fb4"),
    "reaction": ("#fff8f0", "#c2410c"),
    "other": ("#f5f5f5", "#606060"),
}


def youtube_theme_css() -> str:
    """Inject once per page (Streamlit ``st.markdown(..., unsafe_allow_html=True)``)."""
    return f"""
<style>
  :root {{
    --yt-bg: {YT_BG};
    --yt-surface: {YT_SURFACE};
    --yt-text: {YT_TEXT};
    --yt-text-secondary: {YT_TEXT_SECONDARY};
    --yt-border: {YT_BORDER};
    --yt-accent: {YT_ACCENT};
    --yt-accent-soft: {YT_ACCENT_SOFT};
  }}
  .stApp {{
    background-color: {YT_BG};
  }}
  .main .block-container {{
    padding-top: 1.25rem;
    padding-bottom: 2rem;
    max-width: 1280px;
  }}
  [data-testid="stSidebar"] {{
    background: {YT_SIDEBAR};
    border-right: 1px solid {YT_BORDER};
  }}
  [data-testid="stSidebar"] .stMarkdown h5 {{
    color: {YT_TEXT};
  }}
  h1, h2, h3, h4, h5, h6, p, label, .stMarkdown {{
    color: {YT_TEXT};
  }}
  .stCaption, small {{
    color: {YT_TEXT_SECONDARY} !important;
  }}
  div[data-testid="stMetric"] {{
    background: {YT_SURFACE};
    border: 1px solid {YT_BORDER};
    border-radius: 12px;
    padding: 0.5rem 0.75rem;
  }}
  [data-testid="stExpander"] summary {{
    color: {YT_TEXT};
    font-weight: 600;
  }}
  div[data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"] {{
    color: {YT_ACCENT} !important;
    border-bottom-color: {YT_ACCENT} !important;
  }}
  .stButton > button[kind="primary"] {{
    background-color: {YT_ACCENT};
    border-color: {YT_ACCENT};
    color: #fff;
  }}
  .stButton > button[kind="primary"]:hover {{
    background-color: #b80000;
    border-color: #b80000;
  }}
  .stDownloadButton button {{
    border-radius: 18px !important;
    border-color: {YT_BORDER_STRONG} !important;
    color: {YT_TEXT} !important;
    background: {YT_SURFACE} !important;
  }}
  .stDownloadButton button:hover {{
    border-color: {YT_ACCENT} !important;
    color: {YT_ACCENT} !important;
  }}
  .yt-dash-header {{ margin-bottom: 0.25rem; }}
  .yt-dash-title {{
    font-size: 1.5rem;
    font-weight: 700;
    color: {YT_TEXT};
    letter-spacing: -0.02em;
    margin: 0;
  }}
  .yt-dash-subtitle {{
    font-size: 0.9rem;
    color: {YT_TEXT_SECONDARY};
    margin: 0.35rem 0 0 0;
  }}
  .yt-metric-card {{
    background: {YT_SURFACE};
    border-radius: 12px;
    padding: 1rem 1.1rem;
    border: 1px solid {YT_BORDER};
    border-top: 3px solid {YT_ACCENT_SOFT};
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    min-height: 96px;
  }}
  .yt-metric-label {{
    font-size: 0.75rem;
    font-weight: 600;
    color: {YT_TEXT_SECONDARY};
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }}
  .yt-metric-value {{
    font-size: 1.65rem;
    font-weight: 700;
    color: {YT_TEXT};
    line-height: 1.2;
    margin: 0.35rem 0 0 0;
  }}
  .yt-metric-sub {{
    font-size: 0.72rem;
    color: {YT_TEXT_MUTED};
    margin-top: 0.35rem;
  }}
  .yt-filter-heading {{
    font-size: 0.85rem;
    font-weight: 600;
    color: {YT_TEXT};
    margin: 0 0 0.5rem 0;
  }}
  [data-testid="stVerticalBlockBorderWrapper"] {{
    border-color: {YT_BORDER} !important;
    border-radius: 12px !important;
    background: {YT_SURFACE} !important;
  }}
  .yt-network-panel {{
    background: {YT_GRAPH_CANVAS};
    border-radius: 8px;
    width: 100%;
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.04);
  }}
  .yt-network-panel--empty {{
    border: 1px dashed {YT_BORDER_STRONG};
    background: {YT_GRAPH_EMPTY};
  }}
  div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:last-child
    [data-testid="stVerticalBlockBorderWrapper"] {{
    min-height: calc(100vh - 11rem);
  }}
  .yt-network-canvas-slot {{
    width: 100%;
    min-height: 720px;
    margin-top: 0.5rem;
    border-radius: 8px;
    background: {YT_GRAPH_CANVAS};
    border: 1px solid {YT_BORDER};
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.04);
  }}
  .yt-network-canvas-slot--empty {{
    border-style: dashed;
    border-color: {YT_BORDER_STRONG};
    background: {YT_GRAPH_EMPTY};
  }}
  .yt-section-label {{
    font-size: 0.78rem;
    font-weight: 600;
    color: {YT_TEXT_SECONDARY};
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin: 0 0 0.4rem 0;
  }}
  .yt-brand-bar {{
    height: 3px;
    background: linear-gradient(90deg, {YT_ACCENT} 0%, {YT_ACCENT_MID} 50%, {YT_ACCENT} 100%);
    border-radius: 2px;
    margin: 0 0 1rem 0;
  }}
</style>
"""
