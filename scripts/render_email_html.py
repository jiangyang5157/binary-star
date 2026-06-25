#!/usr/bin/env python3
"""
Render a session JSON file to an email-safe HTML template for development/testing.

Usage:
    python scripts/render_email_html.py -f data/prod/sessions/BTCUSDT_session_20260101_120000.json -p data/prod
    python scripts/render_email_html.py -f data/prod/sessions/BTCUSDT_session_20260101_120000.json -p data/prod --open
"""

import os
import sys

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TOOLS_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import argparse
import json
import webbrowser
from pathlib import Path
from datetime import datetime, timezone

from src.utils.pipeline_utils import add_data_path_argument
from src.utils.path_utils import find_project_root
from src.utils.datetime_utils import format_timestamp_for_filename
from src.dashboard.session_html_renderer import SessionRenderer


def main():
    parser = argparse.ArgumentParser(
        description="Render a session JSON to email-safe HTML for development/testing."
    )
    parser.add_argument(
        "--file", "-f",
        required=True,
        help="Path to the session JSON file (e.g., data/prod/sessions/BTCUSDT_session_20260101_120000.json)",
    )
    add_data_path_argument(parser, required=True)
    parser.add_argument(
        "--open", "-o",
        action="store_true",
        help="Open the rendered HTML in the default browser after generation.",
    )
    parser.add_argument(
        "--output", "-O",
        type=str,
        default=None,
        help="Custom output filename (default: auto-generated from session data).",
    )

    args = parser.parse_args()
    project_root = find_project_root()
    data_root = args.path

    # 1. Load session JSON
    session_path = Path(args.file)
    if not session_path.exists():
        # Try relative to project root
        session_path = Path(project_root) / args.file
    if not session_path.exists():
        print(f"Error: Session file not found: {args.file}")
        sys.exit(1)

    try:
        session_data = json.loads(session_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error: Failed to read session JSON: {e}")
        sys.exit(1)

    # 2. Basic validation
    if not isinstance(session_data, dict):
        print("Error: Session JSON is not a dictionary/object.")
        sys.exit(1)

    obs = session_data.get("observation") or {}
    symbol = obs.get("symbol", "UNKNOWN")
    observed_at = obs.get("observed_at", "")
    print(f"Session: {symbol}")
    print(f"Observed: {observed_at or '(unknown)'}")

    # 3. Render HTML via the existing SessionRenderer
    html_body = SessionRenderer.render(session_data)

    # 4. Resolve visual context attachments (swap cid: → file:// for local preview)
    visual_context = obs.get("visual_context") or {}
    attachments = {
        "macro_snapshot": str(visual_context.get("macro_snapshot") or ""),
        "micro_snapshot": str(visual_context.get("micro_snapshot") or ""),
    }

    preview_html = html_body
    for cid, file_path in attachments.items():
        if file_path:
            if not os.path.isabs(file_path):
                abs_path = os.path.abspath(os.path.join(project_root, file_path))
            else:
                abs_path = file_path
            if os.path.exists(abs_path):
                preview_html = preview_html.replace(f"cid:{cid}", f"file://{abs_path}")
                print(f"  Embedded: {cid} → {abs_path}")
            else:
                print(f"  Missing: {cid} ({file_path})")

    # 5. Determine output filename
    if args.output:
        output_filename = args.output
        if not output_filename.endswith(".html"):
            output_filename += ".html"
    else:
        # Generate filename from session metadata
        ts_suffix = format_timestamp_for_filename(observed_at) if observed_at else datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_filename = f"{symbol}_session_{ts_suffix}.html"

    # 6. Write to {data_root}/html/
    output_dir = Path(project_root) / data_root / "html"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_filename
    output_path.write_text(preview_html, encoding="utf-8")

    print(f"\nHTML rendered → {output_path}")
    print(f"  Size: {len(preview_html):,} bytes")

    # 7. Open in browser if requested
    if args.open:
        file_url = output_path.resolve().as_uri()
        webbrowser.open(file_url)
        print(f"  Opened in browser: {file_url}")


if __name__ == "__main__":
    main()
