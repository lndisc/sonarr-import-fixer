FROM python:3.11-alpine

WORKDIR /app

RUN apk add --no-cache su-exec

# Copy the script
COPY sonarr-fix-imports.py /app/
COPY entrypoint.sh /app/

RUN chmod +x /app/entrypoint.sh /app/sonarr-fix-imports.py

# Run as non-root user (will be overridden by PUID/PGID)
ENV PUID=1000
ENV PGID=1000
ENV INTERVAL=300
ENV SONARR_URL=http://sonarr:8989
ENV SONARR_API_KEY=""
ENV DRY_RUN=false

ENTRYPOINT ["/app/entrypoint.sh"]
