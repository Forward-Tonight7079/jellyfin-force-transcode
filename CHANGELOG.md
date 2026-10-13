# Changelog

This file lists all notable changes to the project. It follows
[Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-10-13

### Added
- One `playback …` log line for each PlaybackInfo: the client, the rule (or `rule=none`), the caps,
  and the decision of Jellyfin from its answer — `direct play`, `remux`, or `transcode` with each
  stream (`video copied` / `video -> h264`, `audio -> aac 2ch`) and the reasons. You no longer need
  the Jellyfin dashboard to confirm that a rule works.
- The proxy reads and checks `rules.json` at startup and then every 2 seconds. `loaded N rule(s)` (with
  the rule names) and warnings about misspelled fields appear at once, not at the next playback.

### Changed
- The `playback …` line replaces the `rewrote PlaybackInfo …` line.
- A broken `rules.json` gives one warning with the line and column, and says that the previous good
  rules stay active. Before, the warning repeated on each request and said "passthrough".
- The startup line no longer says "(none mounted = passthrough)" when a file is mounted. The addon
  reports the real state of the rules file.

## [1.0.0] - 2026-10-13

### Added
- New rule schema with two groups: `audio` (`allow`, `deny`, `transcode_to`, `max_channels`) and
  `video` (`allow`, `deny`, `max_bit_depth`, `max_width`). `max_bitrate` stays at the top level.
- `audio.deny` / `video.deny` — codecs that the server must always transcode. One field fixes a device
  that reports a codec but plays it badly, for example `"audio": { "deny": ["opus"] }`.
- Codec lists accept a JSON array (`["aac", "mp3"]`) or a comma string (`"aac,mp3"`).
- Log warnings, one time for each rule: `deprecated field X -> use Y` and `unknown field X (ignored)`.
  Before, a misspelled field did nothing without a message.
- README: "Upgrade from 0.x" table; second real case (Fire tablet, 10-bit HEVC).

### Changed
- `allow` and `deny` also limit the client's transcode codec list. Before, Jellyfin could make a remux
  and copy a blocked codec (seen with Opus over fMP4 HLS). `audio.transcode_to` is now optional.
- `allow` keeps only the codecs that the client also reports. Before, `keep_audio_codecs` replaced the
  client's list and could add codecs that the client did not report.
- The `rewrote PlaybackInfo` log line uses the new names, for example
  `audio(deny=opus) video(max_bit_depth=8)`.

### Deprecated
- The flat 0.x fields still work and map to the new ones: `max_audio_channels` -> `audio.max_channels`,
  `keep_audio_codecs` -> `audio.allow`, `transcode_audio_codec` -> `audio.transcode_to`,
  `keep_video_codecs` -> `video.allow`, `max_video_bit_depth` -> `video.max_bit_depth`,
  `max_width` -> `video.max_width`. The old `max_audio_channels` alone still limits direct play to AAC
  and MP3; the new `audio.max_channels` does not.

## [0.3.0] - 2026-10-12

### Added
- `transcode_audio_codec` rule field — the audio codec(s) that the server may send when it transcodes
  or remuxes (for example `aac`, or `eac3,aac`). It replaces the client's own list. Without it, the
  server can copy a blocked codec during a remux.
- README section "Real cases" with the first case: an LG TV that reports Opus but stutters on it. The
  fix sends AAC, keeps the channel count, and copies the video.
- Example rule `lg-tv-no-opus` in `examples/rules.json`.

### Changed
- `keep_audio_codecs` now works alone. Before, it applied only together with `max_audio_channels`.
  Alone, it blocks direct play of other audio codecs and keeps the channel count.
- `keep_audio_codecs` now applies to every video direct-play entry. Before, it skipped an entry
  without an `AudioCodec` list. Such an entry allows every codec, so the limit had a gap.
- The `rewrote PlaybackInfo` log line shows `transac=…` for `transcode_audio_codec`.

## [0.2.2] - 2026-09-22

### Fixed
- Match `client` and `device` against the human-readable value. The client encodes these values in the
  Authorization header (a space becomes `+` or `%20`, for example `Jellyfin+for+Android`). The proxy
  now decodes them. Before, an exact `client` match with a space (for example
  `"client": "Jellyfin for Android"`) never matched, and the rule was skipped.

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

[1.1.0]: https://github.com/Forward-Tonight7079/jellyfin-force-transcode/releases/tag/v1.1.0
[1.0.0]: https://github.com/Forward-Tonight7079/jellyfin-force-transcode/releases/tag/v1.0.0
[0.3.0]: https://github.com/Forward-Tonight7079/jellyfin-force-transcode/releases/tag/v0.3.0
[0.2.2]: https://github.com/Forward-Tonight7079/jellyfin-force-transcode/releases/tag/v0.2.2
[0.2.1]: https://github.com/Forward-Tonight7079/jellyfin-force-transcode/releases/tag/v0.2.1
[0.2.0]: https://github.com/Forward-Tonight7079/jellyfin-force-transcode/releases/tag/v0.2.0
[0.1.0]: https://github.com/Forward-Tonight7079/jellyfin-force-transcode/releases/tag/v0.1.0
