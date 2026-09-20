# Security Policy

## Reporting a vulnerability

Please report security issues privately through GitHub Security Advisories — use **"Report a
vulnerability"** on the repository's **Security** tab — rather than opening a public issue.

## How this proxy handles traffic

This is a reverse proxy that sits between clients and Jellyfin. By design it:

- rewrites only `POST .../PlaybackInfo` request bodies; all other traffic (including video segments
  and WebSocket) is forwarded unchanged;
- does **not** store or log credentials, tokens, or media/body content — logs contain only the rule
  name, the caps applied and the request path;
- on any error while handling a request, forwards it **unchanged** (fail-safe).

## Deployment guidance

Run the proxy over plain HTTP only on a trusted LAN. For access from outside your network, put it
behind a TLS-terminating reverse proxy (Nginx Proxy Manager, Caddy, Traefik) — do not expose the
plain HTTP port to the internet.
