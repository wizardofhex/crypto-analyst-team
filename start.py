"""
start.py — Launch the Streamlit dashboard and terminal chat together.

Usage:
  python start.py                    # dashboard + haiku chat
  python start.py --model claude-sonnet-4-6  # dashboard + sonnet chat
  python start.py --dashboard-only   # dashboard only
  python start.py --chat-only        # terminal chat only
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser(description="Crypto Analyst Team Launcher")
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5-20251001",
        choices=["claude-haiku-4-5-20251001", "claude-sonnet-4-6"],
        help="Model for the terminal chat (default: haiku)",
    )
    parser.add_argument("--dashboard-only", action="store_true", help="Launch dashboard only")
    parser.add_argument("--chat-only", action="store_true", help="Launch terminal chat only")
    args = parser.parse_args()

    procs = []

    if not args.chat_only:
        print("Starting dashboard at http://localhost:8501 ...")
        dashboard = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "dashboard.py",
             "--server.headless", "true"],
            cwd=str(PROJECT_DIR),
        )
        procs.append(dashboard)

    if not args.dashboard_only:
        print(f"Starting terminal chat (model: {args.model}) ...")
        chat = subprocess.Popen(
            [sys.executable, "main.py", "--model", args.model],
            cwd=str(PROJECT_DIR),
        )
        procs.append(chat)

    try:
        # Wait for whichever process exits first (usually the chat on Ctrl+C)
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()
