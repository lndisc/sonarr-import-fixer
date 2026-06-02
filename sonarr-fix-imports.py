#!/usr/bin/env python3
"""
Sonarr Fix Imports Script
Automatically fixes blocked imports by creating hardlinks and cleaning the queue.

The problem: Downloads with Spanish titles (e.g., "Él y ella (2026)") don't match
Sonarr's series name (e.g., "His & Hers (2026)"), causing import to be blocked.

Solution: Create hardlinks manually from the download folder to the media folder
with proper Sonarr naming, then trigger a rescan and clean the queue.
"""

import os
import re
import json
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

# Configuration (from environment variables)
SONARR_URL = os.environ.get("SONARR_URL", "http://localhost:8989")
SONARR_API_KEY = os.environ.get("SONARR_API_KEY", "")
LOG_FILE = os.environ.get("LOG_FILE", "/var/log/sonarr-fix-imports.log")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

def log(message):
    """Log message to file and stdout"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] {message}"
    print(log_message)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(log_message + "\n")
    except:
        pass

def api_request(endpoint, method="GET", data=None):
    """Make API request to Sonarr"""
    url = f"{SONARR_URL}/api/v3/{endpoint}"
    headers = {"X-Api-Key": SONARR_API_KEY}

    if data:
        headers["Content-Type"] = "application/json"
        data = json.dumps(data).encode('utf-8')

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        log(f"API Error: {e.code} - {error_body[:200]}")
        return None
    except Exception as e:
        log(f"Request Error: {str(e)}")
        return None

def get_blocked_downloads():
    """Get all downloads with importBlocked state"""
    queue = api_request("queue?pageSize=500")
    if not queue or "records" not in queue:
        return []

    blocked = {}
    for item in queue["records"]:
        if item.get("trackedDownloadState") == "importBlocked":
            series_id = item.get("seriesId")
            if series_id not in blocked:
                blocked[series_id] = {
                    "seriesId": series_id,
                    "outputPath": item.get("outputPath"),
                    "queueIds": []
                }
            blocked[series_id]["queueIds"].append(item.get("id"))

    return list(blocked.values())

def get_series_info(series_id):
    """Get series information including path"""
    return api_request(f"series/{series_id}")

def get_episodes(series_id):
    """Get all episodes for a series"""
    return api_request(f"episode?seriesId={series_id}")

def parse_episode_info(filename):
    """Extract season and episode numbers from filename"""
    # Match patterns like S01E05, S1E5, etc.
    match = re.search(r'S(\d+)E(\d+)', filename, re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None

def get_video_files(directory):
    """Get all video files in a directory"""
    video_extensions = {'.mkv', '.mp4', '.avi', '.m4v', '.wmv'}
    files = []

    if not os.path.isdir(directory):
        return files

    for entry in os.listdir(directory):
        path = os.path.join(directory, entry)
        if os.path.isfile(path):
            ext = os.path.splitext(entry)[1].lower()
            if ext in video_extensions:
                files.append(path)

    return files

def generate_sonarr_filename(series, episode, quality="WEBDL-2160p"):
    """Generate filename in Sonarr's naming format"""
    series_title = series.get("title", "Unknown")
    year = series.get("year", "")
    season_num = episode.get("seasonNumber", 0)
    episode_num = episode.get("episodeNumber", 0)
    episode_title = episode.get("title", f"Episode {episode_num}")

    # Clean episode title for filename
    episode_title = re.sub(r'[<>:"/\\|?*]', '', episode_title)

    # Format: "Series (Year) - S01E01 - Episode Title QUALITY.ext"
    if year:
        filename = f"{series_title} ({year}) - S{season_num:02d}E{episode_num:02d} - {episode_title} {quality}"
    else:
        filename = f"{series_title} - S{season_num:02d}E{episode_num:02d} - {episode_title} {quality}"

    return filename

def detect_quality(filename):
    """Detect quality from filename"""
    filename_lower = filename.lower()

    if "2160p" in filename_lower:
        if "remux" in filename_lower:
            return "Remux-2160p"
        elif "bluray" in filename_lower or "bdremux" in filename_lower:
            return "Bluray-2160p"
        elif "web-dl" in filename_lower or "webdl" in filename_lower:
            return "WEBDL-2160p"
        elif "webrip" in filename_lower:
            return "WEBRip-2160p"
        return "HDTV-2160p"
    elif "1080p" in filename_lower:
        if "remux" in filename_lower:
            return "Remux-1080p"
        elif "bluray" in filename_lower or "bdremux" in filename_lower:
            return "Bluray-1080p"
        elif "web-dl" in filename_lower or "webdl" in filename_lower:
            return "WEBDL-1080p"
        elif "webrip" in filename_lower:
            return "WEBRip-1080p"
        return "HDTV-1080p"
    elif "720p" in filename_lower:
        return "HDTV-720p"

    return "Unknown"

def create_hardlink(source, destination):
    """Create a hardlink from source to destination"""
    if DRY_RUN:
        log(f"  [DRY-RUN] Would create hardlink: {destination}")
        return True

    try:
        dest_dir = os.path.dirname(destination)
        os.makedirs(dest_dir, exist_ok=True)

        puid = int(os.environ.get("PUID", 1000))
        pgid = int(os.environ.get("PGID", 1000))
        if os.stat(dest_dir).st_uid != puid:
            os.chown(dest_dir, puid, pgid)

        if os.path.exists(destination):
            os.remove(destination)

        os.link(source, destination)
        return True
    except Exception as e:
        log(f"  Error creating hardlink: {e}")
        return False

def trigger_rescan(series_id):
    """Trigger Sonarr to rescan a series"""
    if DRY_RUN:
        log(f"  [DRY-RUN] Would trigger rescan for series {series_id}")
        return True

    result = api_request("command", method="POST", data={
        "name": "RescanSeries",
        "seriesId": series_id
    })
    return result is not None

def remove_from_queue(queue_ids):
    """Remove items from the Sonarr queue"""
    if not queue_ids:
        return True

    if DRY_RUN:
        log(f"  [DRY-RUN] Would remove {len(queue_ids)} items from queue")
        return True

    result = api_request(
        "queue/bulk?removeFromClient=false&blocklist=false",
        method="DELETE",
        data={"ids": queue_ids}
    )
    return result is not None or result == {}

def process_blocked_series(blocked_item):
    """Process a single blocked series"""
    series_id = blocked_item["seriesId"]
    output_path = blocked_item["outputPath"]
    queue_ids = blocked_item["queueIds"]

    # Get series info
    series = get_series_info(series_id)
    if not series:
        log(f"  Failed to get series info for ID {series_id}")
        return False

    series_title = series.get("title", "Unknown")
    series_path = series.get("path", "")

    log(f"Processing: {series_title}")
    log(f"  Source: {output_path}")
    log(f"  Destination: {series_path}")
    log(f"  Queue items: {len(queue_ids)}")

    if not series_path:
        log(f"  No series path configured, skipping")
        return False

    # Get episodes for mapping
    episodes = get_episodes(series_id)
    if not episodes:
        log(f"  Failed to get episodes, skipping")
        return False

    # Build episode lookup: (season, episode) -> episode_info
    episode_map = {}
    for ep in episodes:
        key = (ep.get("seasonNumber"), ep.get("episodeNumber"))
        episode_map[key] = ep

    # Get video files from download directory (or single file)
    video_extensions = {'.mkv', '.mp4', '.avi', '.m4v', '.wmv'}
    if os.path.isfile(output_path) and os.path.splitext(output_path)[1].lower() in video_extensions:
        video_files = [output_path]
    else:
        video_files = get_video_files(output_path)
    if not video_files:
        log(f"  No video files found in {output_path}")
        return False

    log(f"  Found {len(video_files)} video files")

    # Process each video file
    success_count = 0
    for source_file in video_files:
        filename = os.path.basename(source_file)
        season, episode = parse_episode_info(filename)

        if season is None or episode is None:
            log(f"  Could not parse episode info from: {filename}")
            continue

        episode_info = episode_map.get((season, episode))
        if not episode_info:
            log(f"  No episode found for S{season:02d}E{episode:02d}")
            continue

        # Detect quality and generate destination filename
        quality = detect_quality(filename)
        ext = os.path.splitext(filename)[1]
        dest_filename = generate_sonarr_filename(series, episode_info, quality) + ext
        dest_path = os.path.join(series_path, dest_filename)

        log(f"  S{season:02d}E{episode:02d}: {filename}")
        log(f"    -> {dest_filename}")

        if create_hardlink(source_file, dest_path):
            success_count += 1

    if success_count > 0:
        log(f"  Created {success_count} hardlinks")

        # Trigger rescan
        log(f"  Triggering rescan...")
        trigger_rescan(series_id)

        # Wait a moment for rescan to start
        import time
        time.sleep(2)

        # Remove from queue
        log(f"  Cleaning queue...")
        remove_from_queue(queue_ids)

        return True
    else:
        log(f"  No hardlinks created, skipping queue cleanup")
        return False

def main():
    log("=" * 60)
    log("Sonarr Fix Imports - Starting")
    log("=" * 60)

    if DRY_RUN:
        log("*** DRY RUN MODE - No changes will be made ***")

    # Get blocked downloads
    blocked = get_blocked_downloads()

    if not blocked:
        log("No blocked imports found")
        return 0

    log(f"Found {len(blocked)} series with blocked imports")

    success = 0
    failed = 0

    for item in blocked:
        try:
            if process_blocked_series(item):
                success += 1
            else:
                failed += 1
        except Exception as e:
            log(f"Error processing series {item.get('seriesId')}: {e}")
            failed += 1

    log("=" * 60)
    log(f"Complete: {success} succeeded, {failed} failed")
    log("=" * 60)

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    import sys

    # Check for dry-run flag (overrides environment variable)
    if "--dry-run" in sys.argv:
        DRY_RUN = True

    # Validate API key
    if not SONARR_API_KEY:
        print("ERROR: SONARR_API_KEY environment variable is required")
        sys.exit(1)

    sys.exit(main())
