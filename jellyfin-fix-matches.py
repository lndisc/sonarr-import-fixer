#!/usr/bin/env python3
"""
Jellyfin Fix Matches Script
Fixes series that Jellyfin identified as a different show.

The problem: Sonarr names the folder with the English TVDB title (e.g.
"Marry My Husband") and Jellyfin's scanner matches it by name to an unrelated
series with a similar title. Jellyseerr then looks for the requested
tmdbId/tvdbId, can't find it in Jellyfin and the request stays in PROCESSING
forever, even though every episode is on disk.

Solution: for every Sonarr series with files, compare the ids Sonarr has with
the ids Jellyfin assigned to the same folder. On mismatch, apply Sonarr's ids
in Jellyfin (RemoteSearch/Apply) and, if anything was fixed, run Jellyseerr's
full Jellyfin scan followed by the availability sync.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

SONARR_URL = os.environ.get("SONARR_URL", "http://sonarr:8989")
SONARR_API_KEY = os.environ.get("SONARR_API_KEY", "")
JELLYFIN_URL = os.environ.get("JELLYFIN_URL", "http://jellyfin:8096")
JELLYFIN_API_KEY = os.environ.get("JELLYFIN_API_KEY", "")
JELLYSEERR_URL = os.environ.get("JELLYSEERR_URL", "http://jellyseerr:5055")
JELLYSEERR_API_KEY = os.environ.get("JELLYSEERR_API_KEY", "")
LOG_FILE = os.environ.get("LOG_FILE", "")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
# Safety net: never touch more than this many series in a single run
MAX_FIXES = int(os.environ.get("JELLYFIN_MAX_FIXES", "5"))
# Give up on a series after this many failed attempts (Jellyfin keeps reverting)
MAX_ATTEMPTS = int(os.environ.get("JELLYFIN_MAX_ATTEMPTS", "3"))
STATE_FILE = os.environ.get("JELLYFIN_STATE_FILE", "/tmp/jellyfin-fix-matches.json")


def log(message):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    print(line, flush=True)
    if LOG_FILE:
        try:
            with open(LOG_FILE, "a") as f:
                f.write(line + "\n")
        except OSError:
            pass


def request(url, headers, method="GET", data=None):
    if data is not None:
        headers = {**headers, "Content-Type": "application/json"}
        data = json.dumps(data).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
        return json.loads(body) if body else None


def sonarr(endpoint):
    return request(f"{SONARR_URL}/api/v3/{endpoint}", {"X-Api-Key": SONARR_API_KEY})


def jellyfin(endpoint, method="GET", data=None):
    # Jellyfin 12.x rejects the legacy X-Emby-Token header (401)
    headers = {"Authorization": f'MediaBrowser Token="{JELLYFIN_API_KEY}"'}
    return request(f"{JELLYFIN_URL}{endpoint}", headers, method, data)


def jellyseerr(endpoint, method="GET"):
    return request(f"{JELLYSEERR_URL}/api/v1/{endpoint}", {"X-Api-Key": JELLYSEERR_API_KEY}, method)


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except OSError as e:
        log(f"Could not save state: {e}")


def folder(path):
    return (path or "").rstrip("/").rsplit("/", 1)[-1]


def mismatch(series, item):
    """Return a reason string if Jellyfin's ids don't match Sonarr's, else None."""
    ids = item.get("ProviderIds") or {}
    jf_tvdb, jf_tmdb = ids.get("Tvdb"), ids.get("Tmdb")
    tvdb, tmdb = str(series.get("tvdbId") or ""), str(series.get("tmdbId") or "")
    if jf_tvdb and tvdb:
        return None if jf_tvdb == tvdb else f"tvdb {jf_tvdb} != {tvdb}"
    if jf_tmdb and tmdb:
        return None if jf_tmdb == tmdb else f"tmdb {jf_tmdb} != {tmdb}"
    if not jf_tvdb and not jf_tmdb:
        return "no provider ids"
    return None


def wanted_ids(series):
    ids = {}
    if series.get("tvdbId"):
        ids["Tvdb"] = str(series["tvdbId"])
    if series.get("tmdbId"):
        ids["Tmdb"] = str(series["tmdbId"])
    if series.get("imdbId"):
        ids["Imdb"] = series["imdbId"]
    return ids


def apply_ids(series, item):
    jellyfin(f"/Items/RemoteSearch/Apply/{item['Id']}?ReplaceAllImages=true",
             method="POST", data={"ProviderIds": wanted_ids(series)})
    # The refresh is asynchronous: wait for the new ids to land
    for _ in range(12):
        time.sleep(5)
        current = jellyfin(f"/Items?Ids={item['Id']}&Fields=Path,ProviderIds")["Items"]
        if current and not mismatch(series, current[0]):
            return current[0]
    return None


def run_seerr_job(job_id, timeout=1800):
    jellyseerr(f"settings/jobs/{job_id}/run", method="POST")
    deadline = time.time() + timeout
    time.sleep(10)
    while time.time() < deadline:
        jobs = jellyseerr("settings/jobs")
        if not any(j["id"] == job_id and j.get("running") for j in jobs):
            return True
        time.sleep(15)
    return False


def main():
    if not (JELLYFIN_API_KEY and SONARR_API_KEY):
        log("Jellyfin match check disabled (JELLYFIN_API_KEY not set)")
        return 0

    log("Jellyfin Fix Matches - Starting")
    if DRY_RUN:
        log("*** DRY RUN MODE - No changes will be made ***")

    series_list = [s for s in sonarr("series")
                   if (s.get("statistics") or {}).get("episodeFileCount", 0) > 0]
    items = jellyfin("/Items?Recursive=true&IncludeItemTypes=Series&Fields=Path,ProviderIds")["Items"]
    by_folder = {}
    for item in items:
        by_folder.setdefault(folder(item.get("Path")), []).append(item)

    state = load_state()
    candidates = []
    for series in series_list:
        for item in by_folder.get(folder(series.get("path")), []):
            reason = mismatch(series, item)
            if reason:
                candidates.append((series, item, reason))

    if not candidates:
        log("No mismatched series found")
        return 0

    log(f"Found {len(candidates)} mismatched series")
    if len(candidates) > MAX_FIXES:
        log(f"  More than {MAX_FIXES} mismatches: only the first {MAX_FIXES} will be fixed this run")

    fixed = failed = 0
    for series, item, reason in candidates[:MAX_FIXES]:
        key = item["Id"]
        attempts = state.get(key, 0)
        log(f"Processing: {series['title']} -> Jellyfin thinks '{item.get('Name')}' ({reason})")
        if attempts >= MAX_ATTEMPTS:
            log(f"  Skipped: already failed {attempts} times, needs a manual look")
            failed += 1
            continue
        if DRY_RUN:
            log(f"  [DRY-RUN] Would apply {wanted_ids(series)} to item {key}")
            continue
        try:
            result = apply_ids(series, item)
        except urllib.error.URLError as e:
            result = None
            log(f"  Jellyfin error: {e}")
        if result:
            log(f"  Fixed: now '{result.get('Name')}' {result.get('ProviderIds')}")
            state.pop(key, None)
            fixed += 1
        else:
            state[key] = attempts + 1
            log(f"  Not fixed (attempt {attempts + 1}/{MAX_ATTEMPTS})")
            failed += 1
    save_state(state)

    if fixed and JELLYSEERR_API_KEY:
        # The 'recently added' scan is not enough: Jellyseerr needs the full scan
        log("Running Jellyseerr jellyfin-full-scan...")
        if run_seerr_job("jellyfin-full-scan"):
            log("Running Jellyseerr availability-sync...")
            run_seerr_job("availability-sync")
        else:
            log("  Full scan did not finish in time, skipping availability-sync")
    elif fixed:
        log("JELLYSEERR_API_KEY not set: run a full Jellyfin scan in Jellyseerr by hand")

    log(f"Complete: {fixed} fixed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        DRY_RUN = True
    try:
        sys.exit(main())
    except Exception as e:
        log(f"Jellyfin Fix Matches failed: {e}")
        sys.exit(1)
