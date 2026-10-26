# Match by user

Use this filter when the settings are for one person, on each device of that person.

## The keys

| Key | Value | Changes when |
|---|---|---|
| `user` | the user name, for example `Reggie` | an administrator renames the user |
| `user_id` | the user id, 32 hex digits | never |

```json
{ "name": "kids-stereo",
  "match": { "user": ["Reggie", "Sid"] },
  "audio": { "max_channels": 2 } }
```

`user` is easier to read. `user_id` stays correct after a rename. If you rename a user, the log shows
`rule=none` and the new name.

## How the proxy finds the user

Many apps do not send the user id in the request. The proxy asks Jellyfin `GET /Users/Me` with the
token of the client, and keeps the answer for one hour. See
[What a client sends](playbackinfo.md#the-user-is-often-not-in-the-request).

- `user` is case-sensitive. For a case-insensitive comparison, use a regular expression:
  `"user": "/^reggie$/i"`.
- `user_id` can have dashes or capital letters in the rule. The proxy compares the ids without dashes
  and in lower case.
- Find the user id in the log line `PlaybackInfo from …`, or in **Dashboard → Users** (open the user;
  the id is in the page address).

## User and device together

A user can have a phone and a tablet. To select only the tablet of one user, use both keys:

```json
"match": { "user": "Reggie", "device": "reggie-tablet" }
```
