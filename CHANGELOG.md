# Changelog

This file lists all notable changes to the project. It follows
[Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).

## [0.2.1] - 2026-09-22

### Added
- Log line `PlaybackInfo from client=… device_id=… user_id=… user_agent=…` — it prints one time for
  each new client. It shows the exact values that the proxy parsed. Copy these values into a rule
  `match`. They can differ from the Jellyfin dashboard.

### Changed
- The `rewrote PlaybackInfo` log line now lists every cap that the rule applied (`maxch`, `keepac`,
  `maxw`, `maxbr`, `keepvc`, `maxbits`) and the parsed `client`. Before, it listed only `maxch`,
  `maxw`, and `maxbr`.

## [0.2.0] - 2026-09-22

### Added
- `max_video_bit_depth` rule field — forces video transcode when the source bit depth is higher
  (for example `8` transcodes 10-bit HEVC while 8-bit keeps direct-playing).
- `keep_video_codecs` rule field — a whitelist of video codecs a client may direct-play (like
  `keep_audio_codecs` for audio); other codecs are transcoded.

## [0.1.0] - 2026-09-20

### Added
- Initial release.
- Reverse proxy (mitmproxy) that rewrites `POST .../PlaybackInfo` to force server-side audio and/or
  video transcoding for chosen clients.
- Neutral by default: with no `rules.json` it passes everything through unchanged.
- Matchers `client`, `device_id`, `user_agent`, `user_id` — each an exact string or a `/regex/`
  (with flags, for example `i`).
- Independent audio (`max_audio_channels`, `keep_audio_codecs`) and video (`max_width`,
  `max_bitrate`) caps.
- `LOG=events|full|quiet` (default `events`).
- Multi-arch image (linux/amd64, linux/arm64) published to GHCR by CI; pytest test suite gating the
  build.

[0.2.1]: https://github.com/Forward-Tonight7079/jellyfin-force-transcode/releases/tag/v0.2.1
[0.2.0]: https://github.com/Forward-Tonight7079/jellyfin-force-transcode/releases/tag/v0.2.0
[0.1.0]: https://github.com/Forward-Tonight7079/jellyfin-force-transcode/releases/tag/v0.1.0
