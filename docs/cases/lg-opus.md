# LG TV: the audio stutters on Opus

## Problem

An LG TV (webOS) reports that it plays Opus audio. Jellyfin direct-plays such files. The audio then
stutters badly. When the user lowers the bitrate in the player, the server transcodes the audio to AAC,
and the audio is good. But then the server also transcodes the video, and the video quality is lower.

## Fix

The problem is in the TV, so select the TV by its address. Give the TV a DHCP reservation, then:

```json
{
  "devices": { "lg-tv": ["192.168.1.50"] },
  "rules": [
    { "name": "lg-tv-no-opus",
      "match": { "device": "lg-tv" },
      "audio": { "deny": ["opus"] } }
  ]
}
```

- The server transcodes only the audio. It copies the video without a change, so the CPU load is
  small. The channel count stays the same (5.1 stays 5.1).
- Files with other audio codecs (AAC, AC-3, E-AC-3) still direct-play.
- `deny` also stops a remux that copies the Opus track. The TV also lists Opus for transcoding. Thus,
  without `deny`, the server can send Opus again. (We saw this on Jellyfin 12.1 with fMP4 HLS.)
- To select the output codec, add `"transcode_to": "eac3"` (or `"aac"`). Without it, the server selects
  a codec from the list of the TV.

The same rule works for other audio codecs that a device reports but plays badly, for example
`["dts", "truehd"]`.

## Verify

Play a file with Opus audio. The proxy log must show:

```
jft: playback device=lg-tv … rule=lg-tv-no-opus audio(deny=opus) -> transcode: video copied, audio -> aac (AudioCodecNotSupported)
```
