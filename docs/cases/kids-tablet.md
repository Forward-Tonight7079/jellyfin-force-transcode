# Kids tablet: the video freezes on 7.1 audio

This case is the reason for the proxy.

## Problem 1: audio

A kids' tablet (8.7-inch screen) uses the "Jellyfin for Android" app with the integrated player
(ExoPlayer), because only this player has Picture-in-Picture. The player tells the server that it
plays multichannel E-AC-3. For movies with 7.1 audio, the server copies the audio, and the video
freezes.

## Problem 2: full bitrate on a small screen

Some files direct-play at the full bitrate (for example, 41 Mbps). On an 8.7-inch screen, the picture
is not better. When the tablet uses a phone hotspot, the data flow is too large for the slow
connection, and the video buffers frequently.

## Fix

The tablets connect only by IP address: at home through Wi-Fi, away from home through WireGuard. Each
tablet has a DHCP reservation and its own WireGuard peer. Thus a rule by device applies in each app on
the tablets:

```json
{
  "devices": {
    "reggie-tablet": ["192.168.8.165", "10.1.0.3"],
    "sid-tablet":    ["192.168.8.237", "10.1.0.4"]
  },
  "rules": [
    { "name": "kids-tablets",
      "match": { "device": ["reggie-tablet", "sid-tablet"] },
      "audio": { "max_channels": 2, "allow": ["aac", "mp3"], "transcode_to": "aac" },
      "video": { "max_width": 1344 },
      "max_bitrate": 6000000 }
  ]
}
```

- `audio.max_channels: 2` makes the server downmix the audio to stereo.
- `audio.allow` makes sure that the tablet gets only AAC or MP3, not E-AC-3.
- `audio.transcode_to: "aac"` selects AAC. Without it, the server sent MP3, because the app lists MP3
  first.
- `video.max_width: 1344` is near the screen width (1340 pixels).
- `max_bitrate: 6000000` (6 Mbps) is sufficient for this screen and for a phone hotspot.

Picture-in-Picture still works, and the media files do not change.

## Verify

Play a movie with 7.1 audio. The proxy log must show the device and the audio as `aac 2ch`:

```
jft: playback device=reggie-tablet user='Reggie' client='Jellyfin for Android' rule=kids-tablets … -> transcode: video -> h264, audio -> aac 2ch (…)
```
