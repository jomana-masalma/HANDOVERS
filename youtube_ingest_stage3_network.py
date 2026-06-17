"""
Stage 3: build YouTube network tables from normalized data.

No YouTube API calls. Reads Stage 2 canonical file (or Stage 1 JSON if Stage 2
was not run yet) and writes node/edge CSV files for network analysis tools
(NetworkX, Gephi, etc.).

Network design :
- Nodes: videos and channels
- Edges:
  - channel --published--> video
  - video --same_channel--> video (videos from the same channel)
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd


@dataclass
class Stage3Config:
    input_dir: Path = field(default_factory=lambda: Path("./youtube_out"))
    stage2_dir: Path = field(default_factory=lambda: Path("./youtube_out/stage2"))
    output_dir: Path = field(default_factory=lambda: Path("./youtube_out/stage3_network"))


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_canonical_records(cfg: Stage3Config) -> List[Dict[str, Any]]:
    # Prefer Stage 2 merged file; fall back to concatenating Stage 1 JSONL files.
    stage2_path = cfg.stage2_dir / "canonical_all_videos.jsonl"
    if stage2_path.exists():
        logging.info("Loading canonical records from Stage 2: %s", stage2_path)
        return read_jsonl(stage2_path)

    logging.warning("Stage 2 file not found; falling back to Stage 1 JSONL files.")
    return read_jsonl(cfg.input_dir / "out_canonical_curated_videos.jsonl") + read_jsonl(
        cfg.input_dir / "out_canonical_search_videos.jsonl"
    )


def build_nodes(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    nodes: Dict[str, Dict[str, Any]] = {}

    for row in records:
        video_id = row.get("post_id")
        channel_id = row.get("author_id")
        if video_id:
            nodes[f"video:{video_id}"] = {
                "node_id": f"video:{video_id}",
                "node_type": "video",
                "platform_id": video_id,
                "label": (row.get("title_or_text") or "")[:80],
                "url": row.get("url"),
            }
        if channel_id:
            nodes[f"channel:{channel_id}"] = {
                "node_id": f"channel:{channel_id}",
                "node_type": "channel",
                "platform_id": channel_id,
                "label": (row.get("context_metrics") or {}).get("channel_title") or channel_id,
                "url": None,
            }
    return list(nodes.values())


def build_edges(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    edges: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str, str]] = set()

    def add_edge(source: str, target: str, edge_type: str, weight: float = 1.0) -> None:
        key = (source, target, edge_type)
        if key in seen:
            return
        seen.add(key)
        edges.append(
            {"source": source, "target": target, "edge_type": edge_type, "weight": weight}
        )

    # Group videos by channel to create same_channel edges (light co-occurrence layer).
    by_channel: Dict[str, List[str]] = {}
    for row in records:
        video_id = row.get("post_id")
        channel_id = row.get("author_id")
        if not video_id or not channel_id:
            continue
        video_node = f"video:{video_id}"
        channel_node = f"channel:{channel_id}"
        add_edge(channel_node, video_node, "published")
        by_channel.setdefault(channel_id, []).append(video_node)

    for channel_id, video_nodes in by_channel.items():
        if len(video_nodes) < 2:
            continue
        # Connect each pair once (undirected logic exported as two directed edges is optional;
        # here we link the first video as hub to keep the graph readable for small samples).
        hub = video_nodes[0]
        for other in video_nodes[1:]:
            add_edge(hub, other, "same_channel")

    return edges


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def run_stage3(cfg: Stage3Config) -> Path:
    records = load_canonical_records(cfg)
    if not records:
        raise SystemExit("No canonical records found. Run Stage 1 (and ideally Stage 2) first.")

    nodes = build_nodes(records)
    edges = build_edges(records)

    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        cfg.output_dir / "nodes.csv",
        nodes,
        ["node_id", "node_type", "platform_id", "label", "url"],
    )
    write_csv(
        cfg.output_dir / "edges.csv",
        edges,
        ["source", "target", "edge_type", "weight"],
    )

    summary = {
        "stage": 3,
        "video_nodes": sum(1 for n in nodes if n["node_type"] == "video"),
        "channel_nodes": sum(1 for n in nodes if n["node_type"] == "channel"),
        "edges_total": len(edges),
        "edges_published": sum(1 for e in edges if e["edge_type"] == "published"),
        "edges_same_channel": sum(1 for e in edges if e["edge_type"] == "same_channel"),
    }
    summary_path = cfg.output_dir / "stage3_network_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Optional pandas sanity check — helps the user verify imports quickly.
    pd.DataFrame(nodes).to_csv(cfg.output_dir / "nodes_pandas_check.csv", index=False)

    logging.info(
        "Stage 3 complete: %s nodes, %s edges -> %s",
        len(nodes),
        len(edges),
        cfg.output_dir,
    )
    return summary_path


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stage 3 — build YouTube network node/edge tables.")
    p.add_argument("--input-dir", type=Path, default=Path("./youtube_out"))
    p.add_argument("--stage2-dir", type=Path, default=Path("./youtube_out/stage2"))
    p.add_argument("--output-dir", type=Path, default=Path("./youtube_out/stage3_network"))
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)
    cfg = Stage3Config(
        input_dir=args.input_dir.resolve(),
        stage2_dir=args.stage2_dir.resolve(),
        output_dir=args.output_dir.resolve(),
    )
    run_stage3(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
