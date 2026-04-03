#!/usr/bin/env python3
"""
publish_episode.py — Add a new episode to the Daily Intelligence Briefing podcast.

Usage:
    python publish_episode.py <mp3_path> [--title "Episode Title"] [--date 2026-04-02]

Examples:
    python publish_episode.py ~/Downloads/PodcastBrief_2026-04-02.mp3
    python publish_episode.py ~/Downloads/PodcastBrief_2026-04-02.mp3 --title "April 2 Briefing"
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_DIR = Path(__file__).parent.resolve()
EPISODES_DIR = REPO_DIR / "episodes"
FEED_FILE = REPO_DIR / "feed.xml"


def get_mp3_duration_seconds(mp3_path: Path) -> int:
    """Get duration in seconds using ffprobe if available, else estimate from file size."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(mp3_path)],
            capture_output=True, text=True, check=True
        )
        return int(float(result.stdout.strip()))
    except Exception:
        # Estimate: ~1 MB/min at 128kbps
        size_mb = mp3_path.stat().st_size / (1024 * 1024)
        return int(size_mb * 60)


def format_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def get_feed_base_url() -> str:
    """Read base URL from feed.xml <link> element."""
    tree = ET.parse(FEED_FILE)
    root = tree.getroot()
    channel = root.find("channel")
    link = channel.find("link")
    url = link.text.strip().rstrip("/")
    if "FEED_BASE_URL" in url:
        print("ERROR: feed.xml still has placeholder URL. Run setup first.")
        sys.exit(1)
    return url


def get_existing_guids() -> set:
    """Parse existing episode GUIDs from feed.xml."""
    tree = ET.parse(FEED_FILE)
    root = tree.getroot()
    ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
    guids = set()
    for item in root.find("channel").findall("item"):
        guid = item.find("guid")
        if guid is not None:
            guids.add(guid.text)
    return guids


def build_item_xml(title: str, mp3_filename: str, pub_date: datetime,
                   file_size: int, duration_sec: int, base_url: str) -> str:
    episode_url = f"{base_url}/episodes/{mp3_filename}"
    pub_date_rfc = format_datetime(pub_date)
    duration_str = format_duration(duration_sec)
    description = (
        f"Daily Intelligence Briefing for {pub_date.strftime('%B %-d, %Y')}. "
        "Covering markets, technology, and geopolitics."
    )
    return f"""
    <item>
      <title>{title}</title>
      <description>{description}</description>
      <pubDate>{pub_date_rfc}</pubDate>
      <guid isPermaLink="false">{episode_url}</guid>
      <link>{episode_url}</link>
      <enclosure url="{episode_url}" length="{file_size}" type="audio/mpeg"/>
      <itunes:duration>{duration_str}</itunes:duration>
      <itunes:title>{title}</itunes:title>
      <itunes:summary>{description}</itunes:summary>
      <itunes:explicit>false</itunes:explicit>
    </item>"""


def insert_episode_into_feed(item_xml: str):
    """Insert a new <item> as the first episode in the RSS feed."""
    feed_text = FEED_FILE.read_text(encoding="utf-8")

    # Insert before </channel>
    insertion_point = feed_text.rfind("</channel>")
    if insertion_point == -1:
        print("ERROR: Could not find </channel> in feed.xml")
        sys.exit(1)

    new_feed = feed_text[:insertion_point] + item_xml + "\n  " + feed_text[insertion_point:]
    FEED_FILE.write_text(new_feed, encoding="utf-8")


def git_commit_and_push(mp3_filename: str, episode_title: str):
    env = os.environ.copy()

    def run(cmd, **kwargs):
        result = subprocess.run(cmd, cwd=REPO_DIR, env=env, capture_output=True,
                                text=True, **kwargs)
        if result.returncode != 0:
            print(f"ERROR running {' '.join(cmd)}:\n{result.stderr}")
            sys.exit(1)
        return result.stdout.strip()

    print("Staging files...")
    run(["git", "add", f"episodes/{mp3_filename}", "feed.xml"])

    print("Committing...")
    run(["git", "commit", "-m", f"Add episode: {episode_title}"])

    print("Pushing to GitHub...")
    run(["git", "push", "origin", "main"])
    print("Pushed successfully.")


def main():
    parser = argparse.ArgumentParser(description="Publish a podcast episode.")
    parser.add_argument("mp3", help="Path to the MP3 file")
    parser.add_argument("--title", help="Episode title (default: derived from filename)")
    parser.add_argument("--date", help="Episode date YYYY-MM-DD (default: today)")
    parser.add_argument("--no-push", action="store_true",
                        help="Stage and commit but don't push (for testing)")
    args = parser.parse_args()

    mp3_path = Path(args.mp3).expanduser().resolve()
    if not mp3_path.exists():
        print(f"ERROR: File not found: {mp3_path}")
        sys.exit(1)
    if mp3_path.suffix.lower() != ".mp3":
        print(f"ERROR: Expected an MP3 file, got: {mp3_path.name}")
        sys.exit(1)

    # Determine date
    if args.date:
        episode_date = datetime.strptime(args.date, "%Y-%m-%d").replace(
            hour=6, tzinfo=timezone.utc)
    else:
        # Try to parse date from filename like PodcastBrief_2026-04-02.mp3
        match = re.search(r"(\d{4}-\d{2}-\d{2})", mp3_path.name)
        if match:
            episode_date = datetime.strptime(match.group(1), "%Y-%m-%d").replace(
                hour=6, tzinfo=timezone.utc)
        else:
            episode_date = datetime.now(timezone.utc).replace(
                hour=6, minute=0, second=0, microsecond=0)

    # Determine title
    if args.title:
        title = args.title
    else:
        title = f"Daily Intelligence Briefing — {episode_date.strftime('%B %-d, %Y')}"

    # Destination filename (keep original or normalize)
    mp3_filename = mp3_path.name
    dest_path = EPISODES_DIR / mp3_filename

    base_url = get_feed_base_url()
    episode_url = f"{base_url}/episodes/{mp3_filename}"

    # Check for duplicate
    existing = get_existing_guids()
    if episode_url in existing:
        print(f"Episode already in feed: {episode_url}")
        print("Use --title or --date to publish a different episode.")
        sys.exit(0)

    # Copy MP3
    EPISODES_DIR.mkdir(exist_ok=True)
    if dest_path != mp3_path:
        print(f"Copying {mp3_path.name} → episodes/")
        shutil.copy2(mp3_path, dest_path)
    else:
        print(f"MP3 already in episodes/ directory.")

    file_size = dest_path.stat().st_size
    print(f"File size: {file_size / 1024 / 1024:.1f} MB")

    # Get duration
    duration_sec = get_mp3_duration_seconds(dest_path)
    print(f"Duration: {format_duration(duration_sec)}")

    # Build and insert item
    item_xml = build_item_xml(title, mp3_filename, episode_date,
                               file_size, duration_sec, base_url)
    insert_episode_into_feed(item_xml)
    print(f"Updated feed.xml with: {title}")

    if args.no_push:
        print("\n--no-push: skipping git commit/push.")
        print(f"Episode staged. Run 'git add episodes/{mp3_filename} feed.xml && git push' when ready.")
        return

    git_commit_and_push(mp3_filename, title)

    print(f"\nDone! Episode live at:")
    print(f"  {episode_url}")
    print(f"\nRSS feed: {base_url}/feed.xml")


if __name__ == "__main__":
    main()
