# Match by app

Use this filter when the problem is in one player app. Other apps on the same device are good.

## The keys

| Key | What it identifies | Changes when |
|---|---|---|
| `client` | the type of app, for example `Jellyfin for Android` | never for one app |
| `device_id` | one installation of an app (some apps: installation + user) | depends on the app (see below) |
| `user_agent` | the app and its version | each app update |

Examples of `client`: `Jellyfin for Android`, `Jellyfin Android TV`, `Jellyfin Web`, `Findroid`,
`Moonfin for Android`. Read the exact value in the `PlaybackInfo from …` line of the log.

## One app on one device

Use the device and the app together:

```json
{ "name": "tablet-integrated-player",
  "match": { "device": "reggie-tablet", "client": "Jellyfin for Android" },
  "audio": { "max_channels": 2 } }
```

## All installations of one app

```json
{ "name": "any-android-app", "match": { "client": "/Android/" }, "audio": { "max_channels": 2 } }
```

`/Android/` fits `Jellyfin for Android` and `Jellyfin Android TV`.

## `device_id`: one installation

`device_id` comes from the app, and each app makes it differently. Results of our tests on one tablet:

- **Jellyfin for Android:** 16 hex digits of the device, then the user id. Sign out and sign in: no
  change. Another user: only the user part changes. A new installation: no change. To select the
  device for each user, match the first part: `"device_id": "/^0bf2cfd8a68d6046/"`.
- **Moonfin:** a random UUID for each installation. Another user: no change. A new installation: a new
  UUID.
- **Jellyfin Android TV:** a different value for each user on one box.
- **Jellyfin Web:** a value in the storage of the browser. It changes when you clear the browser data.

If a rule with `device_id` stops to fit, the log shows `rule=none` and the new value in the
`PlaybackInfo from …` line.

## `user_agent`

The value contains the app version, so it changes with each update. Use a `/regex/`:

```json
"match": { "user_agent": "/okhttp/i" }
```
