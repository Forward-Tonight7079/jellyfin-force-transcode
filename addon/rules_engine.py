"""Pure rules/matching/rewrite logic for jellyfin-force-transcode.

No mitmproxy dependency, so it is unit-testable with plain Python. rewrite.py is
a thin mitmproxy adapter around these functions.
"""
import ipaddress, json, logging, os, re
from urllib.parse import unquote_plus

log = logging.getLogger("force-transcode")

_FLAGS = {"i": re.I, "s": re.S, "m": re.M, "x": re.X}
_re_cache = {}
_file_cache = {}  # path -> (mtime, config)  (last good config)
_file_state = {}  # path -> last reported state, so each state is logged one time


# --- matching -------------------------------------------------------------

def _compile(spec):
    if spec in _re_cache:
        return _re_cache[spec]
    rx = None
    try:
        last = spec.rfind("/")
        flags = 0
        for ch in spec[last + 1:]:
            flags |= _FLAGS.get(ch, 0)
        rx = re.compile(spec[1:last], flags)
    except Exception as e:
        log.warning("bad regex %r: %s" % (spec, e))
    _re_cache[spec] = rx
    return rx


def value_matches(pattern, value):
    """Plain string => exact match; "/regex/[flags]" => re.search (flexible)."""
    if value is None:
        return False
    pattern = str(pattern)
    if len(pattern) >= 2 and pattern[0] == "/" and pattern.rfind("/") > 0:
        rx = _compile(pattern)
        return rx is not None and rx.search(value) is not None
    return value == pattern


def _as_list(pattern):
    return pattern if isinstance(pattern, list) else [pattern]


def rule_matches(match, ctx):
    """Every key must fit (AND). A list of values for one key means any of them (OR)."""
    if not match:
        return True
    for key, pattern in match.items():
        if key == "ip":
            if not ip_in(ctx.get("ip"), pattern):
                return False
        elif key == "user_id":
            if not any(value_matches(_norm_pattern(p), ctx.get(key)) for p in _as_list(pattern)):
                return False
        elif not any(value_matches(p, ctx.get(key)) for p in _as_list(pattern)):
            return False
    return True


def _norm_pattern(p):
    # A plain user id in a rule may have dashes or capitals; a /regex/ stays as written.
    p = str(p)
    return p if p.startswith("/") else _norm_id(p)


def pick_rule(rules, ctx):
    return next((r for r in (rules or []) if isinstance(r, dict)
                 and rule_matches(r.get("match", {}), ctx)), None)


def auth_fields(auth):
    # 'MediaBrowser Client="X", Device="Y", DeviceId="Z", Version="1", Token="..."'
    # The client encodes the values (a space becomes "+" or "%20"). Decode them,
    # so a rule can match the human-readable name, for example "Jellyfin for Android".
    return {k: unquote_plus(v) for k, v in re.findall(r'(\w+)="([^"]*)"', auth or "")}


def build_ctx(auth, user_agent, query_user_id, body, ip=None):
    uid = query_user_id
    if uid is None and isinstance(body, dict):
        uid = body.get("UserId")
    f = auth_fields(auth)
    return {"client": f.get("Client"), "device_id": f.get("DeviceId"),
            "device_name": f.get("Device"), "user_agent": user_agent or "",
            "user_id": _norm_id(uid), "user": None, "ip": ip, "device": None}


def _norm_id(uid):
    # Jellyfin writes ids with and without dashes, in any case. Compare one form.
    return uid.replace("-", "").lower() if isinstance(uid, str) and uid else uid


# --- client IP and devices ------------------------------------------------

DEFAULT_TRUSTED = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"
_net_cache = {}


def _net(spec):
    spec = str(spec).strip()
    if spec not in _net_cache:
        try:
            _net_cache[spec] = ipaddress.ip_network(spec, strict=False)
        except ValueError:
            _net_cache[spec] = None
    return _net_cache[spec]


def _addr(value):
    try:
        a = ipaddress.ip_address(str(value).strip().strip("[]"))
    except ValueError:
        return None
    # "::ffff:192.168.1.5" is an IPv4 client on a dual-stack socket.
    return a.ipv4_mapped if getattr(a, "ipv4_mapped", None) else a


def ip_in(ip, specs):
    """True if ip is in any of the IP addresses or networks (CIDR) in specs."""
    a = _addr(ip) if ip else None
    if a is None:
        return False
    for spec in _as_list(specs):
        n = _net(spec)
        if n is not None and a.version == n.version and a in n:
            return True
    return False


def client_ip(peer, forwarded_for=None, real_ip=None, trusted=DEFAULT_TRUSTED):
    """The client address. Headers are used only when the peer is a trusted proxy.
    In X-Forwarded-For, the right-most address that is not trusted is the client."""
    peer_a = _addr(peer) if peer else None
    if peer_a is None:
        return None
    trusted = [t for t in str(trusted or "").split(",") if t.strip()]
    if not ip_in(str(peer_a), trusted):
        return str(peer_a)
    hops = [h.strip() for h in (forwarded_for or "").split(",") if _addr(h)]
    for h in reversed(hops):
        if not ip_in(h, trusted):
            return str(_addr(h))
    if hops:
        return str(_addr(hops[0]))
    if real_ip and _addr(real_ip):
        return str(_addr(real_ip))
    return str(peer_a)


_DEVICE_KEYS = ("ip", "device_id", "client", "user_agent", "user", "user_id")


def _device_spec(spec):
    # "name": ["192.168.1.5", "10.1.0.3"]  is short for  "name": {"ip": [...]}
    if isinstance(spec, dict):
        return spec
    return {"ip": spec}


def resolve_device(devices, ctx):
    """Name of the first device whose spec fits. Inside one spec any key may fit (OR)."""
    for name, spec in (devices or {}).items():
        for key, pattern in _device_spec(spec).items():
            if key == "ip":
                if ip_in(ctx.get("ip"), pattern):
                    return name
            elif key in _DEVICE_KEYS and any(value_matches(p, ctx.get(key)) for p in _as_list(pattern)):
                return name
    return None


def config_notes(cfg):
    """Warnings for the devices section and for match keys and device names in rules."""
    notes = []
    devices = cfg.get("devices") or {}
    if not isinstance(devices, dict):
        return ['"devices" must be an object (ignored)']
    for name, spec in devices.items():
        for key, pattern in _device_spec(spec).items():
            if key not in _DEVICE_KEYS:
                notes.append("device=%s: unknown key %s (ignored)" % (name, key))
            elif key == "ip":
                for p in _as_list(pattern):
                    if _net(p) is None:
                        notes.append("device=%s: bad IP or network %r" % (name, p))
    for r in cfg.get("rules") or []:
        if not isinstance(r, dict):
            continue
        rname = r.get("name", "?")
        for key, pattern in (r.get("match") or {}).items():
            if key not in _MATCH_KEYS:
                notes.append("rule=%s: unknown match key %s (the rule never fits)" % (rname, key))
            elif key == "device":
                for d in _as_list(pattern):
                    if isinstance(d, str) and not d.startswith("/") and d not in devices:
                        notes.append("rule=%s: device %r is not in \"devices\"" % (rname, d))
            elif key == "ip":
                for p in _as_list(pattern):
                    if _net(p) is None:
                        notes.append("rule=%s: bad IP or network %r" % (rname, p))
    return notes


_MATCH_KEYS = ("client", "device_id", "user_agent", "user_id", "user", "ip", "device")


# --- rule schema ----------------------------------------------------------
#
# 1.x schema: transforms live in two groups plus one top-level cap.
#   "audio": {"allow", "deny", "transcode_to", "max_channels"}
#   "video": {"allow", "deny", "max_width", "max_bit_depth"}
#   "max_bitrate"
# The flat 0.x fields still work. normalize() maps them and reports them, so the
# log can show the new spelling.

_AUDIO_KEYS = ("allow", "deny", "transcode_to", "max_channels")
_VIDEO_KEYS = ("allow", "deny", "max_width", "max_bit_depth")
_RULE_KEYS = ("name", "match", "audio", "video", "max_bitrate")

# old flat field -> (group, new key)
_DEPRECATED = {
    "max_audio_channels":    ("audio", "max_channels"),
    "keep_audio_codecs":     ("audio", "allow"),
    "transcode_audio_codec": ("audio", "transcode_to"),
    "keep_video_codecs":     ("video", "allow"),
    "max_width":             ("video", "max_width"),
    "max_video_bit_depth":   ("video", "max_bit_depth"),
}

_ALL_VIDEO = "h264,hevc,mpeg4,vp9,av1,vc1"
_warned = set()


def codec_list(value):
    """A list or a comma string -> list of lower-case codecs. Empty -> []."""
    if value is None:
        return []
    items = value if isinstance(value, list) else str(value).split(",")
    return [str(c).strip().lower() for c in items if str(c).strip()]


def _int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def normalize(rule):
    """Return (spec, notes). spec = {"audio": {...}, "video": {...}, "max_bitrate": int|None}.
    notes = human-readable warnings (deprecated or unknown fields)."""
    notes = []
    audio = dict(rule.get("audio") or {}) if isinstance(rule.get("audio"), dict) else {}
    video = dict(rule.get("video") or {}) if isinstance(rule.get("video"), dict) else {}
    groups = {"audio": audio, "video": video}

    for old, (grp, key) in _DEPRECATED.items():
        if old in rule:
            notes.append("deprecated field %s -> use %s.%s" % (old, grp, key))
            groups[grp].setdefault(key, rule[old])
    # 0.x behaviour: max_audio_channels alone also limited direct play to aac,mp3.
    if "max_audio_channels" in rule and "keep_audio_codecs" not in rule:
        audio.setdefault("allow", "aac,mp3")

    for k in rule:
        if k not in _RULE_KEYS and k not in _DEPRECATED:
            notes.append("unknown field %s (ignored)" % k)
    for grp, keys in (("audio", _AUDIO_KEYS), ("video", _VIDEO_KEYS)):
        for k in groups[grp]:
            if k not in keys:
                notes.append("unknown field %s.%s (ignored)" % (grp, k))

    spec = {
        "audio": {"allow": codec_list(audio.get("allow")),
                  "deny": codec_list(audio.get("deny")),
                  "transcode_to": codec_list(audio.get("transcode_to")),
                  "max_channels": _int(audio.get("max_channels"))},
        "video": {"allow": codec_list(video.get("allow")),
                  "deny": codec_list(video.get("deny")),
                  "max_width": _int(video.get("max_width")),
                  "max_bit_depth": _int(video.get("max_bit_depth"))},
        "max_bitrate": _int(rule.get("max_bitrate")),
    }
    return spec, notes


def rule_notes_once(rule):
    """Warnings for a rule, only the first time that this rule content is seen."""
    key = json.dumps(rule, sort_keys=True, default=str)
    if key in _warned:
        return []
    _warned.add(key)
    return normalize(rule)[1]


# --- log helpers ----------------------------------------------------------

def describe_ctx(ctx):
    """Show the identity that the proxy parsed. Use these exact values in a
    rule `match`. The values can differ from the Jellyfin dashboard."""
    return ("device=%s ip=%s user=%r user_id=%r client=%r device_id=%r user_agent=%r"
            % (ctx.get("device") or "unknown", ctx.get("ip"), ctx.get("user"), ctx.get("user_id"),
               ctx.get("client"), ctx.get("device_id"), ctx.get("user_agent")))


def describe_rule(rule):
    """List the caps that a rule applies, in the 1.x spelling. This mirrors apply_rule."""
    spec, _ = normalize(rule)
    parts = []
    for grp in ("audio", "video"):
        sub = []
        for k, v in spec[grp].items():
            if v is None or v == []:
                continue
            sub.append("%s=%s" % (k, ",".join(v) if isinstance(v, list) else v))
        if sub:
            parts.append("%s(%s)" % (grp, " ".join(sub)))
    if spec["max_bitrate"] is not None:
        parts.append("max_bitrate=%s" % spec["max_bitrate"])
    return " ".join(parts) if parts else "no-op"


# --- rewrite --------------------------------------------------------------

def _codec_profiles(dp):
    cps = dp.get("CodecProfiles")
    if not isinstance(cps, list):
        cps = []; dp["CodecProfiles"] = cps
    return cps


def _limit_codecs(dp, field, allow, deny, transcode_to, fallback, cp_type, never_cond):
    """Apply allow/deny/transcode_to to one stream kind (field = AudioCodec or VideoCodec).

    Direct play: the client may direct-play only allowed, not denied codecs.
    Transcode:   the same limit applies to the client's transcode list, because
                 Jellyfin copies the source stream (remux) when its codec is in that
                 list. transcode_to, when set, replaces the list."""
    open_entry = False
    for d in (dp.get("DirectPlayProfiles") or []):
        if d.get("Type") != "Video":
            continue
        cur = codec_list(d.get(field))
        if allow:
            cur = [c for c in cur if c in allow] if cur else list(allow)
        if not cur:
            open_entry = True   # no list = every codec; deny needs a codec profile
            continue
        d[field] = ",".join(c for c in cur if c not in deny)

    if deny and open_entry:
        # An entry without a codec list allows every codec. A condition that never
        # holds makes Jellyfin treat the denied codecs as not direct-playable.
        _codec_profiles(dp).append({"Type": cp_type, "Codec": ",".join(deny),
                                    "Conditions": [dict(never_cond, IsRequired=True)]})

    for tp in (dp.get("TranscodingProfiles") or []):
        if tp.get("Type") != "Video":
            continue
        if transcode_to:
            tp[field] = ",".join(transcode_to)
            continue
        cur = codec_list(tp.get(field))
        if not cur:
            continue
        keep = [c for c in cur if c not in deny and (not allow or c in allow)]
        # Nothing left in the client's list: send an allowed codec, else the fallback.
        tp[field] = ",".join(keep or [c for c in allow if c not in deny] or [fallback])


def apply_rule(rule, dp):
    """Mutate a DeviceProfile in place per the rule. Returns True if changed."""
    spec, _ = normalize(rule)
    a, v = spec["audio"], spec["video"]
    changed = False

    if a["allow"] or a["deny"] or a["transcode_to"]:
        _limit_codecs(dp, "AudioCodec", a["allow"], a["deny"], a["transcode_to"], "aac",
                      "VideoAudio", {"Condition": "LessThanEqual", "Property": "AudioChannels", "Value": "0"})
        changed = True

    ch = a["max_channels"]
    if ch is not None:
        for tp in (dp.get("TranscodingProfiles") or []):
            if tp.get("Type") == "Video":
                tp["MaxAudioChannels"] = str(ch)
        _codec_profiles(dp).append(
            {"Type": "VideoAudio",
             "Codec": "aac,ac3,eac3,dts,truehd,mp3,flac,opus,vorbis,dca",
             "Conditions": [{"Condition": "LessThanEqual", "Property": "AudioChannels",
                             "Value": str(ch), "IsRequired": True}]})
        changed = True

    if v["allow"] or v["deny"]:
        _limit_codecs(dp, "VideoCodec", v["allow"], v["deny"], [], "h264",
                      "Video", {"Condition": "LessThanEqual", "Property": "Width", "Value": "0"})
        changed = True

    if v["max_width"] is not None:
        _codec_profiles(dp).append(
            {"Type": "Video", "Codec": _ALL_VIDEO,
             "Conditions": [{"Condition": "LessThanEqual", "Property": "Width",
                             "Value": str(v["max_width"]), "IsRequired": True}]})
        changed = True

    if v["max_bit_depth"] is not None:
        _codec_profiles(dp).append(
            {"Type": "Video", "Codec": _ALL_VIDEO,
             "Conditions": [{"Condition": "LessThanEqual", "Property": "VideoBitDepth",
                             "Value": str(v["max_bit_depth"]), "IsRequired": True}]})
        changed = True

    if spec["max_bitrate"] is not None:
        dp["MaxStreamingBitrate"] = spec["max_bitrate"]
        changed = True

    return changed


def _report(path, key, level, msg):
    """Log msg only when the state of the rules file changes."""
    if _file_state.get(path) == key:
        return
    _file_state[path] = key
    log.log(level, msg)


def load_config(path):
    """Read {"devices": {...}, "rules": [...]} from a JSON file (mtime-cached).
    Missing => empty (passthrough). A broken file keeps the last good config.
    Each state change is logged one time."""
    empty = {"rules": [], "devices": {}}
    try:
        st = os.stat(path)
    except FileNotFoundError:
        _file_cache.pop(path, None)
        _report(path, "missing", logging.INFO,
                "no rules file at %s: passthrough (the proxy changes nothing)" % path)
        return empty
    ent = _file_cache.get(path)
    if ent is not None and ent[0] == st.st_mtime:
        return ent[1]
    try:
        with open(path) as f:
            data = json.load(f)
        rules = data.get("rules", [])
        if not isinstance(rules, list):
            raise ValueError('"rules" must be a list')
        devices = data.get("devices") or {}
        cfg = {"rules": rules, "devices": devices if isinstance(devices, dict) else {}}
    except Exception as e:
        prev = ent[1] if ent else empty
        n = len(prev["rules"])
        keep = ("keeping the previous %d rule(s)" % n) if n else "passthrough (no rules active)"
        _report(path, ("error", st.st_mtime), logging.WARNING,
                "rules file error in %s: %s; %s" % (path, e, keep))
        return prev
    _file_cache[path] = (st.st_mtime, cfg)
    names = ", ".join(str(r.get("name", "?")) for r in rules if isinstance(r, dict))
    dev = (", %d device(s)" % len(cfg["devices"])) if cfg["devices"] else ""
    _report(path, ("ok", st.st_mtime), logging.INFO,
            "loaded %d rule(s)%s from %s: %s" % (len(rules), dev, path, names or "-"))
    for note in config_notes(cfg):
        log.warning(note)
    return cfg


def load_rules(path):
    return load_config(path)["rules"]


# --- Jellyfin decision (PlaybackInfo response) -------------------------------

def _is_video_reason(r):
    return (r.startswith("Video") or r.startswith("UnknownVideo") or r in (
        "ContainerBitrateExceedsLimit", "SubtitleCodecNotSupported", "RefFramesNotSupported",
        "AnamorphicVideoNotSupported", "InterlacedVideoNotSupported"))


def _is_audio_reason(r):
    return r.startswith("Audio") or r.startswith("SecondaryAudio") or r.startswith("UnknownAudio")


def describe_outcome(resp):
    """One short phrase for what Jellyfin decided, from a PlaybackInfo response body.
    Returns None if the body has no usable media source."""
    if not isinstance(resp, dict):
        return None
    if resp.get("ErrorCode"):
        return "error %s" % resp["ErrorCode"]
    sources = resp.get("MediaSources") or []
    if not sources or not isinstance(sources[0], dict):
        return None
    ms = sources[0]
    if ms.get("SupportsDirectPlay"):
        return "direct play"
    url = ms.get("TranscodingUrl") or ""
    if not url:
        return "direct stream" if ms.get("SupportsDirectStream") else None
    q = {}
    if "?" in url:
        for kv in url.split("?", 1)[1].split("&"):
            k, _, v = kv.partition("=")
            q[k.lower()] = unquote_plus(v)
    reasons = [r for r in q.get("transcodereasons", "").split(",") if r]
    if not reasons:
        return "remux (video and audio copied)"
    vcodec = codec_list(q.get("videocodec"))[:1]
    acodec = codec_list(q.get("audiocodec"))[:1]
    video = ("video -> %s" % vcodec[0]) if vcodec and any(map(_is_video_reason, reasons)) else "video copied"
    audio = ("audio -> %s" % acodec[0]) if acodec and any(map(_is_audio_reason, reasons)) else "audio copied"
    ch = q.get("transcodingmaxaudiochannels")
    if ch and audio != "audio copied":
        audio += " %sch" % ch
    return "transcode: %s, %s (%s)" % (video, audio, ", ".join(reasons))
