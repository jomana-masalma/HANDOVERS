# Handover package — YouTube pipeline (Stage 1–3 + dashboards)

This folder is a self-contained copy of the YouTube work. The saved results can be opened without an API key.

## Safety / quota note (important)

- **Safe (no API calls)**: `run_dashboard.bat`, `youtube_dashboard_streamlit.py`, `final_video_ids_visualization.py`, `youtube_ingest_stage2_normalize.py`, `youtube_ingest_stage3_network.py`
- **Uses API quota**: `youtube_ingest_stage1.py`, `youtube_ingest_stage1_comments.py`, `youtube_ingest_comments_optional.py`
- **Uses OAuth, not just an API key**: `youtube_ingest_transcripts_optional.py`

Opening a `.py` file does not call the API. A call happens only when you run a script from the quota list. See `NOT_TO_DO.md`.

## Contents

| Item | Purpose |
|------|---------|
| `youtube_ingest_stage1.py` | Downloads curated videos, their channels, and the “critical thinking” search into `youtube_out` |
| `youtube_ingest_stage1_comments.py` | Same kind of download (videos, channels, search). The comments dashboard reads the video list from this file |
| `youtube_ingest_comments_optional.py` | **This is the comment-text download.** It calls `commentThreads.list` and writes `out_commentthreads_raw.json` and `out_commentthreads_flat.csv` |
| `youtube_ingest_transcripts_optional.py` | Optional: captions, with an OAuth client file |
| `youtube_ingest_stage2_normalize.py` | Checks the Stage 1 files and merges curated videos with search videos (no API) |
| `youtube_ingest_stage3_network.py` | Builds `nodes.csv` and `edges.csv` for channels and videos (no API). Separate from the reply network |
| `youtube_dashboard_streamlit.py` | Dashboard 1: tables and charts of videos, channels, and search results in `youtube_out` |
| `final_video_ids_visualization.py` | Starts dashboard 2. Run this name; it opens the file below |
| `final video-ids visualization.py` | Dashboard 2: saved comments, transcripts when present, and the reply network |
| `youtube_streamlit_reply_network.py` | Draws the reply network for dashboard 2 |
| `youtube_streamlit_theme.py` | Colours for dashboard 2 |

To download comment text, run **`youtube_ingest_comments_optional.py`**. The saved comments already in the folder are `out_video_comments.jsonl` and `out_video_comments_round_three.jsonl`.

| Item | Purpose |
|------|---------|
| `out_video_comments.jsonl` | First saved batch of comment text, one comment per line |
| `out_video_comments_round_three.jsonl` | Later saved batch of comment text, same fields |
| `youtube_out/` | Saved Stage 1 files, plus Stage 2 and Stage 3. See the tables below |
| `requirements.txt` | Python packages. `pyvis` and the lines under it are for the reply network |
| `run_dashboard.bat` | Windows launcher. Choose 1 for dashboard 1, or 2 for dashboard 2 |
| `NOT_TO_DO.md` | How to avoid spending API quota by accident |

## Quick start (view results only — recommended first)

On Windows, double-click `run_dashboard.bat`.

- Choose **1** for videos, channels, and search. In the sidebar, set **Output folder** to `./youtube_out` and click **Reload data**.
- Choose **2** for comments and the reply network. In the sidebar, set **Data folder** to `youtube_out`.

From PowerShell:

```powershell
streamlit run youtube_dashboard_streamlit.py
streamlit run final_video_ids_visualization.py
```

The two comment files are in the main folder. Dashboard 2 reads `out_video_comments.jsonl` from the data folder, and the later batch from `Comments three round/out_video_comments_round_three.jsonl` inside that folder. GitHub will not display these large files in the browser; download them or open them from the dashboard.

## Files in youtube_out

| Item | Purpose |
|------|---------|
| `out_videos_raw.json` | The 10 curated videos, as returned by the API |
| `out_videos_flat.csv` | Those videos in a table: title, channel, date, views, likes, comment count |
| `out_channels_raw.json` | The curated channels, as returned by the API |
| `out_channels_flat.csv` | Those channels in a table: title, subscribers, video count |
| `out_search_raw.json` | Search hits for “critical thinking” |
| `out_search_enriched_videos.json` | Those search hits with views, likes, and duration filled in |
| `out_search_enriched_channels.json` | Channels for the search hits |
| `out_search_enriched_channels_flat.csv` | Those search channels in a table |
| `out_canonical_curated_videos.jsonl` | Curated videos, one per line, for Stage 2. Label: `curated_videos` |
| `out_canonical_search_videos.jsonl` | Search videos, one per line, for Stage 2 |

## youtube_out/stage2

Stage 2 does not call YouTube. It checks the Stage 1 files and writes one merged list. Read the report first. Use the merged list as the input for Stage 3. The dashboards do not open this folder.

| Item | Purpose |
|------|---------|
| `canonical_all_videos.jsonl` | One line per video, curated and search together (55 lines: 10 curated, 45 search). Each line has the title, URL, channel, views, likes, comment count, and where the video came from. This is the file Stage 3 reads |
| `stage2_validation_report.json` | The check on that merge: 55 records, 0 errors. Open this first if a later step looks wrong |

Run it again, with no API key, from the main folder:

```powershell
python youtube_ingest_stage2_normalize.py --input-dir ./youtube_out
```

## youtube_out/stage3_network

Stage 3 does not call YouTube. It turns the Stage 2 list into a channel–video network. This is not the comment reply network in dashboard 2. A channel is linked to the videos it published, and videos from the same channel are linked to each other. Open `nodes.csv` and `edges.csv` in Excel, or load them in Gephi or NetworkX.

| Item | Purpose |
|------|---------|
| `nodes.csv` | One row per channel and per video: id, type (`video` or `channel`), name, and URL. The saved file has 49 videos and 43 channels |
| `edges.csv` | One row per link: source, target, and type. `published` means the channel published that video (49 links). `same_channel` means two videos belong to one channel (11 links) |
| `stage3_network_summary.json` | The counts above in one small file: 49 video nodes, 43 channel nodes, 60 edges. Read this before drawing the network |
| `nodes_pandas_check.csv` | A short copy of the node list, written only to confirm the table loaded. You can ignore it for the analysis |

Run it again, with no API key, after Stage 2:

```powershell
python youtube_ingest_stage3_network.py --input-dir ./youtube_out
```

## Full pipeline (when an API key is available)

```powershell
$env:YOUTUBE_API_KEY="YOUR_OWN_KEY"
python youtube_ingest_stage1.py --out-dir ./youtube_out
python youtube_ingest_stage2_normalize.py --input-dir ./youtube_out
python youtube_ingest_stage3_network.py --input-dir ./youtube_out
```

Stage 2 and Stage 3 can be run again on the saved files. They do not call the API.

## Optional enrichments (comments + transcripts)

Public comments. The default stop is 10 videos and 200 threads each. The comments already used by dashboard 2 are the two `.jsonl` files in the main folder.

```powershell
$env:YOUTUBE_API_KEY="YOUR_OWN_KEY"
python youtube_ingest_comments_optional.py --out-dir ./youtube_out --max-videos 10 --max-comments-per-video 200
```

Captions need an OAuth client file. An API key does not return transcript text.

```powershell
python youtube_ingest_transcripts_optional.py --out-dir ./youtube_out --client-secrets .\client_secrets.json --max-videos 10
```
