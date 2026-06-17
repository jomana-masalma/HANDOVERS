# Handover package — YouTube pipeline (Stage 1–3 + dashboard)

This folder is a **self-contained copy** to continue the YouTube network work.

## Safety / quota note (important)

- **Safe (no API calls)**: `youtube_dashboard_streamlit.py`, `youtube_ingest_stage2_normalize.py`, `youtube_ingest_stage3_network.py`
- **Uses API quota**: `youtube_ingest_stage1.py` 

## Contents

| Item | Purpose |
|------|---------|
| `youtube_ingest_stage1.py` | Live API ingestion (videos, channels, search) |
| `youtube_ingest_comments_optional.py` | Optional: download public comments via `commentThreads.list` |
| `youtube_ingest_transcripts_optional.py` | Optional: captions/transcripts via OAuth (only when permitted) |
| `youtube_ingest_stage2_normalize.py` | Validate + merge canonical records (no API) |
| `youtube_ingest_stage3_network.py` | Build node/edge CSVs for network analysis (no API) |
| `youtube_dashboard_streamlit.py` | Read-only dashboard for `youtube_out/` |
| `youtube_out/` | Saved outputs from a completed Stage 1 run |
| `requirements.txt` | Python dependencies |
| `run_dashboard.bat` | One-click dashboard launcher (Windows) |
| `.env.example` | API key variable name only (no secret) |
| `NOT_TO_DO.md` | Avoid accidental API quota use |

## Quick start (view results only — recommended first)

```powershell
cd handover
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run youtube_dashboard_streamlit.py
```

In the sidebar, set **Output folder** to `./youtube_out` and click **Reload data**.

If `./youtube_out` is missing/empty, either:
- copy the prepared outputs into `handover/youtube_out/`, or
- run Stage 1 once (requires API key) to regenerate.

## Full pipeline (when API key is available)

```powershell
# Use your own Google Cloud YouTube Data API v3 key (handover does NOT include keys).
$env:YOUTUBE_API_KEY="YOUR_OWN_KEY"
python youtube_ingest_stage1.py --out-dir ./youtube_out --open-report
python youtube_ingest_stage2_normalize.py --input-dir ./youtube_out
python youtube_ingest_stage3_network.py --input-dir ./youtube_out
streamlit run youtube_dashboard_streamlit.py
```

## Optional enrichments (comments + transcripts)

### Public comments (API key)

```powershell
# Uses your own API key; writes into youtube_out/
$env:YOUTUBE_API_KEY="YOUR_OWN_KEY"
python youtube_ingest_comments_optional.py --out-dir ./youtube_out --max-videos 10 --max-comments-per-video 200
```

### Captions / transcripts (OAuth required)

Transcripts are not exposed as plain text via the API-key flow.
If you have permission and an OAuth client, you can fetch caption tracks and download them:

```powershell
python youtube_ingest_transcripts_optional.py --out-dir ./youtube_out --client-secrets .\\client_secrets.json --max-videos 10
```

## Output locations

- **Stage 1** → `youtube_out/` (raw JSON, CSV, JSONL)
- **Stage 2** → `youtube_out/stage2/` (merged canonical + validation report)
- **Stage 3** → `youtube_out/stage3_network/` (`nodes.csv`, `edges.csv`, summary JSON)

## Notes 

- Opening `.py` files does **not** call the API; only **running** Stage 1 does.
- Stage 2 and Stage 3 are safe to re-run anytime on saved files.
- Comment threads and playlist items were intentionally out of scope for Stage 1 (quota + scope); see `handover report.md` in the parent folder for future work.
