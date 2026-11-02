# sonarr-import-fixer

Automatically fixes Sonarr blocked imports caused by filename/title mismatches by creating hardlinks with correct naming and triggering a rescan.

## The Problem

Sonarr marks downloads as `importBlocked` when the downloaded filename doesn't match the series title in its database. A common case: a series is downloaded with a localized title (e.g. `"Él y ella (2026)"`) but Sonarr knows it as `"His & Hers (2026)"`.

Sonarr won't import the file, and the queue stays permanently blocked.

## The Solution

This container runs a Python script on a configurable interval that:

1. Queries the Sonarr API for items in `importBlocked` state
2. Gets the correct destination path for each blocked series from Sonarr
3. Detects the video quality from the filename (2160p, 1080p, etc.)
4. Creates a **hardlink** with the correct Sonarr naming convention directly in the series folder
5. Triggers a Sonarr rescan
6. Removes the blocked entry from the queue

## Optional: fix series Jellyfin matched to the wrong show

Sonarr names folders with the English TVDB title, and Jellyfin's scanner sometimes
matches that folder to an unrelated series with a similar name (e.g. `Marry My Husband`
→ *30 Days Till I Marry My Husband's Nemesis*). Jellyseerr then can't find the requested
id in Jellyfin and the request stays in *processing* forever.

If `JELLYFIN_API_KEY` is set, each run also:

1. Compares the TVDB/TMDB ids Sonarr has for each series with the ids Jellyfin assigned
   to the same folder
2. On mismatch, applies Sonarr's ids in Jellyfin (`RemoteSearch/Apply`) and waits for them
3. If anything was fixed and `JELLYSEERR_API_KEY` is set, runs Jellyseerr's
   `jellyfin-full-scan` and then `availability-sync`

At most `JELLYFIN_MAX_FIXES` series are changed per run, and a series that fails
`JELLYFIN_MAX_ATTEMPTS` times is skipped (logged) until the container restarts.

## Requirements

- The container must share the **same filesystem** as Sonarr and your download client, since hardlinks only work within the same filesystem. This typically means mounting the same root `/data` volume.

## Usage

Add to your `docker-compose.yml`:

```yaml
sonarr-fixer:
  image: imorcillo/sonarr-fixer:latest
  container_name: sonarr-fixer
  environment:
    - PUID=1000
    - PGID=1000
    - TZ=Europe/Madrid
    - SONARR_URL=http://sonarr:8989
    - SONARR_API_KEY=your_api_key_here
    - INTERVAL=1800
    - DRY_RUN=false
  volumes:
    - /path/to/your/data:/data
  restart: always
```

> **Tip:** Start with `DRY_RUN=true` and check the logs to verify it detects and maps your blocked files correctly before enabling it for real.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SONARR_URL` | `http://sonarr:8989` | Sonarr base URL |
| `SONARR_API_KEY` | *(required)* | Sonarr API key |
| `INTERVAL` | `300` | Seconds between runs |
| `DRY_RUN` | `false` | If `true`, logs actions without making changes |
| `PUID` | `1000` | User ID for file ownership |
| `PGID` | `1000` | Group ID for file ownership |
| `JELLYFIN_URL` | `http://jellyfin:8096` | Jellyfin base URL |
| `JELLYFIN_API_KEY` | *(empty: disabled)* | Jellyfin API key; enables the wrong-match check |
| `JELLYSEERR_URL` | `http://jellyseerr:5055` | Jellyseerr base URL |
| `JELLYSEERR_API_KEY` | *(empty)* | Jellyseerr API key; triggers the rescan after a fix |
| `JELLYFIN_MAX_FIXES` | `5` | Max series changed per run |
| `JELLYFIN_MAX_ATTEMPTS` | `3` | Failed attempts before giving up on a series |
| `LOG_FILE` | *(empty)* | Optional log file path inside the container |

## Getting your Sonarr API key

Sonarr → Settings → General → API Key

## Logs

Both scripts log to stdout (`docker logs sonarr-fixer`). To also log to a file, mount a
**directory** (mounting a file path that doesn't exist yet makes Docker create a
directory with that name) and set `LOG_FILE`:

```yaml
environment:
  - LOG_FILE=/logs/sonarr-fixer.log
volumes:
  - ./logs:/logs
```
