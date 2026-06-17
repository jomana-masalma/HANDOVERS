# NOT TO DO (handover folder)

## Do not run Stage 1 unless you mean to use API quota

`youtube_ingest_stage1.py` makes **live YouTube Data API v3** calls.

Safe without API key:
- `youtube_dashboard_streamlit.py` (reads `youtube_out/` only)
- `youtube_ingest_stage2_normalize.py`
- `youtube_ingest_stage3_network.py`

## Do not commit secrets

Keep real API keys in your local environment or `.env` — not in this shared folder.
