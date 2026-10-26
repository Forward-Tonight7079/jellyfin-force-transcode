# Fire tablet: the player crashes on 10-bit HEVC

## Problem

A Fire tablet reports that it plays HEVC. It plays 8-bit HEVC well. But on 10-bit HEVC
(`hevc (Main 10)`), Jellyfin direct-plays the file, and the player crashes with
`NO_EXCEEDS_CAPABILITIES`.

## Fix

Set a limit for the bit depth, not for the codec:

```json
{ "rules": [
    { "name": "fire-tablet-no-10bit",
      "match": { "client": "Jellyfin Android" },
      "video": { "max_bit_depth": 8 } }
] }
```

This rule uses `client`, so it applies to each device with this app. To select only the tablet, use
`device` (see [Match by device](../match-device.md)).

`"video": { "deny": ["hevc"] }` also stops the crash, but it transcodes all HEVC, also the files that
play well.

## Verify

For a 10-bit file the proxy log shows
`-> transcode: video -> h264, audio copied (VideoBitDepthNotSupported)`. For an 8-bit file it shows
`-> direct play`.
