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

## Getting your Sonarr API key

Sonarr → Settings → General → API Key

## Logs

The script logs to stdout (visible via `docker logs sonarr-fixer`) and optionally to a file if you mount one:

```yaml
volumes:
  - ./logs/sonarr-fix-imports.log:/var/log/sonarr-fix-imports.log
  - /path/to/your/data:/data
```
