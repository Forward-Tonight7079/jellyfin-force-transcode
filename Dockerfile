# jellyfin-force-transcode
# Self-contained image: the PlaybackInfo-rewrite addon is baked in; no config is.
# With no rules.json mounted the proxy does nothing (passthrough).
# Mount a rules.json at /addon/rules.json to force audio and/or video transcoding.
FROM mitmproxy/mitmproxy:12.2.3

LABEL org.opencontainers.image.title="jellyfin-force-transcode" \
      org.opencontainers.image.description="Reverse proxy that rewrites Jellyfin PlaybackInfo to force server-side audio and/or video transcoding for chosen clients — something Jellyfin has no built-in setting for." \
      org.opencontainers.image.source="https://github.com/Forward-Tonight7079/jellyfin-force-transcode" \
      org.opencontainers.image.licenses="MIT"

COPY addon/ /addon/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

USER root
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
USER mitmproxy

# JELLYFIN_URL is required and has no default. LISTEN_PORT is the internal port.
# LOG: events (default) | full | quiet — see README.
ENV LISTEN_PORT=8080 \
    LOG=events

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
  CMD python -c "import os,socket; socket.create_connection(('127.0.0.1', int(os.environ.get('LISTEN_PORT','8080'))), 2)" || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
