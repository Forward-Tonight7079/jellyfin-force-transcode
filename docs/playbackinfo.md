# What a client sends

Before a playback, each Jellyfin client sends `POST /Items/{id}/PlaybackInfo`. The request tells the
server what the client can play. The server uses this data to select direct play, remux, or
transcoding. The proxy changes only this request.

## A real request

This request came from the "Jellyfin for Android" app on a tablet. The token is removed.

```
POST /Items/9037b9e3-…/PlaybackInfo
Host: 192.168.8.198:8097
X-Real-IP: 192.168.8.165
X-Forwarded-For: 192.168.8.165
Authorization: MediaBrowser Client="Jellyfin+for+Android", Version="2.7.3",
               DeviceId="0bf2cfd8a68d604660074fe7-97b7-4dad-b922-fb24e4e3cb08",
               Device="Redmi+Pad+SE+8.7", Token="***"
User-Agent: Jellyfin for Android/2.7.3 via jellyfin-sdk-kotlin (OkHttp/4.12.0)
```

```json
{ "MaxStreamingBitrate": 140000000,
  "StartTimeTicks": 12563760000,
  "AutoOpenLiveStream": true,
  "DeviceProfile": { … } }
```

The `DeviceProfile` (about 11 KB) lists the containers, codecs, and subtitle formats that the client
can play:

- `DirectPlayProfiles`: what the client can play from the file without a change.
- `TranscodingProfiles`: what the client accepts when the server transcodes. Jellyfin can also copy a
  stream into this format (remux), if the codec is in the list.
- `CodecProfiles`: limits, for example the number of audio channels or the bit depth.

The proxy changes these lists. Then Jellyfin makes its decision from the changed profile.

## Where each match key comes from

| Match key | Source | Example |
|---|---|---|
| `client` | `Client="…"` in the `Authorization` header | `Jellyfin for Android` |
| `device_id` | `DeviceId="…"` in the `Authorization` header | `0bf2cfd8a68d6046…` |
| `user_agent` | the `User-Agent` header | `Jellyfin for Android/2.7.3 …` |
| `user_id` | `userId` in the request address, `UserId` in the body, or the token | `60074fe797b74dadb922fb24e4e3cb08` |
| `user` | the token: the proxy asks Jellyfin `GET /Users/Me` | `Reggie` |
| `ip` | the connection, or `X-Forwarded-For` / `X-Real-IP` from a trusted proxy | `192.168.8.165` |
| `device` | the `devices` section of `rules.json` (usually from `ip`) | `reggie-tablet` |

The proxy decodes the values in the `Authorization` header. `Jellyfin+for+Android` becomes
`Jellyfin for Android`.

## The user is often not in the request

Many apps do not send the user id. In the request above, there is no user. The browser and some apps
(for example, Moonfin) send `userId` in the address. Each request has a token, and the token belongs to
one user. Thus the proxy asks Jellyfin `GET /Users/Me` with the token of the client. The proxy keeps
the answer for one hour. The proxy sends the auth headers of the client without a change, so Jellyfin
does not record a new device. If the request fails, `user` stays empty, and the playback continues.

## The structure of `DeviceId` is different in each app

We tested two apps on one tablet:

| Action | Jellyfin for Android | Moonfin |
|---|---|---|
| Format | 16 hex digits of the device + the user id | a random UUID |
| Sign out, then sign in as the same user | no change | no change |
| Sign in as a different user | the user part changes | no change |
| Remove and install the app again | no change | not tested (an older installation had a different UUID) |

Thus `DeviceId` is not a good identifier of the hardware. See [Match by device](match-device.md).

## How to see the values of your clients

Read the proxy log. For each new identity, the proxy writes one line:

```
jft: PlaybackInfo from device=unknown ip=192.168.8.165 user='Reggie' user_id='60074fe7…' client='Jellyfin for Android' device_id='0bf2cfd8a68d6046…' user_agent='…'
```

Copy the values from this line into your `match`. The Jellyfin dashboard can show different strings.
