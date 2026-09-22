# Security Policy

## Reporting a vulnerability

Report security issues privately through GitHub Security Advisories. Use **"Report a vulnerability"**
on the repository's **Security** tab. Do not open a public issue.

## How this proxy handles traffic

This proxy sits between clients and Jellyfin. By design:

- It rewrites only `POST .../PlaybackInfo` request bodies. It forwards all other traffic unchanged,
  including video segments and WebSocket.
- It does not store or log credentials, tokens, or media content. The logs contain only the rule
  name, the caps that it applied, and the request path.
- On any error while it handles a request, it forwards the request unchanged (fail-safe).

## Deployment guidance

Run the proxy over plain HTTP only on a trusted LAN. For access from outside your network, put the
proxy behind a TLS reverse proxy (Nginx Proxy Manager, Caddy, or Traefik). Do not expose the plain
HTTP port to the internet.
