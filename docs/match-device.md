# Match by device

Use this filter when the problem is in the hardware or in the network of one device. The rule then
applies in each app on that device.

## Why the network identifies the device

A request contains no hardware identifier. Each app sends its own values, and the apps change them
for different reasons (see [What a client sends](playbackinfo.md)). The network is different. You
control it, and it gives each device a permanent address:

- **At home:** the router gives a device the same IP address each time (a DHCP reservation for the MAC
  address of the device).
- **Away from home, through a VPN:** WireGuard gives each peer a fixed address. Tailscale and ZeroTier
  also give each device a fixed address. The key or the account on the device decides the address.

Thus the IP address identifies the device for each app.

## Configuration

Write the devices one time in the `devices` section. Then use the device names in rules:

```json
{
  "devices": {
    "reggie-tablet":  ["192.168.8.165", "10.1.0.3"],
    "sid-tablet":     ["192.168.8.237", "10.1.0.4"],
    "living-room-tv": ["192.168.8.50"]
  },
  "rules": [
    { "name": "kids-tablets",
      "match": { "device": ["reggie-tablet", "sid-tablet"] },
      "audio": { "max_channels": 2 },
      "video": { "max_width": 1344 },
      "max_bitrate": 6000000 },
    { "name": "tv-no-opus",
      "match": { "device": "living-room-tv" },
      "audio": { "deny": ["opus"] } }
  ]
}
```

- Each device has a list of addresses: one for the home network, one for the VPN.
- An address can also be a network in CIDR format, for example `"192.168.20.0/24"` or
  `"fd00:1234::/64"`.
- You can also use the `ip` key directly in a rule: `"match": { "ip": ["10.1.0.0/24"] }`.
- The log shows the device name: `playback device=reggie-tablet …`. A device that is not in the list
  shows as `device=unknown ip=…`. Copy that address into `devices`.

## Give each device a permanent address

1. **Home network:** on the router, add a DHCP reservation for the MAC address of the device.
2. **Android and iOS:** these systems use a random MAC address for each Wi-Fi network. The random address
   is usually permanent for one network, but it can change (for example, after you remove the network).
   For a reliable reservation, select the device MAC for your home network. On Android: **Settings →
   Wi-Fi → (your network) → Privacy → Use device MAC**.
3. **Repeaters:** give the repeater network the same name (SSID) as the main network. Then the MAC
   setting on the device applies to both.
4. **VPN:** use one peer (WireGuard) or one device entry (Tailscale) for each device. Do not share one
   peer between two devices.

## Behind a reverse proxy

If a reverse proxy (NPM, Caddy, Traefik, nginx) is in front of this proxy, the connection comes from
the reverse proxy, not from the client. The proxy then reads the client address from `X-Forwarded-For`
(or `X-Real-IP`), but only when the connection comes from a trusted address.

- `TRUSTED_PROXIES` sets the trusted addresses. The default is the private networks:
  `127.0.0.0/8, ::1/128, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7`.
- In `X-Forwarded-For`, the proxy uses the right-most address that is not trusted.
- Make sure that your reverse proxy sends `X-Forwarded-For` or `X-Real-IP`. If it does not, each client
  has the address of the reverse proxy.

A client can send a false `X-Forwarded-For` value. This changes only the transcoding for that client.
The rules are not a security control.

## Limits

- **The public internet without a VPN:** the address of a mobile network changes often. Many people can
  also share one address (CGNAT). The IP address does not identify a device there. Use
  [Match by user](match-user.md), or give the device a separate server address.
- **IPv6 privacy addresses:** many systems change their IPv6 address each day. Connect to Jellyfin with
  the IPv4 address, or put the IPv6 network (`/64`) in `devices`.
- **Docker:** in some configurations (for example, IPv6 or hairpin NAT), Docker shows the address of
  its gateway for each client. Then the log shows the same address for all clients.

## Other keys for a device

If the IP address is not permanent, a device entry can use other keys. The device fits when **one**
of its keys fits (logical OR):

```json
"devices": {
  "reggie-tablet": { "ip": ["192.168.8.165", "10.1.0.3"],
                     "device_id": "/^0bf2cfd8a68d6046/" }
}
```

The keys are `ip`, `device_id`, `client`, `user_agent`, `user`, and `user_id`. These keys depend on the
app. See [Match by app](match-app.md).
