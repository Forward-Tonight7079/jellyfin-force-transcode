# Matching guide

A rule in `rules.json` has two parts: `match` selects the playbacks, and the other fields tell the
server what to transcode. This guide is about `match`: how to select the correct playbacks.

## Contents

1. [What a client sends](playbackinfo.md): the request that the proxy reads, and the values that you
   can match.
2. [Match by device](match-device.md): one TV, one tablet, in any app.
3. [Match by app](match-app.md): one player app, or one installation of an app.
4. [Match by user](match-user.md): one person, on any device.
5. Real cases:
   - [Kids tablet: the video freezes on 7.1 audio](cases/kids-tablet.md)
   - [LG TV: the audio stutters on Opus](cases/lg-opus.md)
   - [Fire tablet: the player crashes on 10-bit HEVC](cases/fire-10bit.md)

## Three questions for each playback

Each playback has three properties. A rule can use one of them or a combination:

| Property | Question | Match keys |
|---|---|---|
| Device | Which hardware, on which network? | `device`, `ip` |
| App | Which player? | `client`, `device_id`, `user_agent` |
| User | Who watches? | `user`, `user_id` |

## Find where the problem is

Select the match key from the location of the problem:

| The problem is in… | Example | Use |
|---|---|---|
| The hardware of the device. It occurs in each app. | A TV cannot decode Opus. | `device` |
| One player app on the device. Other apps are good. | The integrated player freezes, but the web player is good. | `device` + `client` |
| The network of the device. | A tablet on a phone hotspot buffers. | `device` |
| The preference of one person. | Stereo for the kids' account on each device. | `user` |

## An important difference: device and app installation

Jellyfin calls a value `DeviceId`, but this value identifies an **installation of an app**, not the
hardware. Two apps on one tablet send two different values. Some apps also change the value for each
user. Thus, to select one physical device, use [`device`](match-device.md). Use `device_id` only to
select one app on one device.

## How the proxy uses `match`

- The proxy reads the rules from top to bottom. It applies the **first** rule whose `match` fits, and
  then it stops.
- A `match` fits when **each** key in it fits (logical AND).
- A list of values for one key fits when **one** of the values fits (logical OR):
  `"user": ["Reggie", "Sid"]`.
- An empty `match: {}` fits each playback. Put such a rule last, as the default rule.
- A plain string must be equal to the value. A `/regex/` value is a regular expression (Python
  `re.search`). The flag `i` after the last slash makes the comparison case-insensitive.
- The proxy writes a warning at startup for an unknown key in `match`, and for a device name that is
  not in `devices`.
