"""Pure rules/matching/rewrite logic for jellyfin-force-transcode.

No mitmproxy dependency, so it is unit-testable with plain Python. rewrite.py is
a thin mitmproxy adapter around these functions.
"""
import json, logging, os, re
from urllib.parse import unquote_plus

log = logging.getLogger("force-transcode")

_FLAGS = {"i": re.I, "s": re.S, "m": re.M, "x": re.X}
_re_cache = {}
_file_cache = {}  # path -> (mtime, rules)


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


def rule_matches(match, ctx):
    if not match:
        return True
    for key, pattern in match.items():
        if not value_matches(pattern, ctx.get(key)):
            return False
    return True


def pick_rule(rules, ctx):
    return next((r for r in (rules or []) if rule_matches(r.get("match", {}), ctx)), None)


def auth_fields(auth):
    # 'MediaBrowser Client="X", Device="Y", DeviceId="Z", Version="1", Token="..."'
    # The client encodes the values (a space becomes "+" or "%20"). Decode them,
    # so a rule can match the human-readable name, for example "Jellyfin for Android".
    return {k: unquote_plus(v) for k, v in re.findall(r'(\w+)="([^"]*)"', auth or "")}


def build_ctx(auth, user_agent, query_user_id, body):
    uid = query_user_id
    if uid is None and isinstance(body, dict):
        uid = body.get("UserId")
    f = auth_fields(auth)
    return {"client": f.get("Client"), "device_id": f.get("DeviceId"),
            "user_agent": user_agent or "", "user_id": uid}


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
    return ("client=%r device_id=%r user_id=%r user_agent=%r"
            % (ctx.get("client"), ctx.get("device_id"),
               ctx.get("user_id"), ctx.get("user_agent")))


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


def load_rules(path):
    """Read rules from a JSON file (mtime-cached). Missing/broken => [] (passthrough)."""
    try:
        st = os.stat(path)
        ent = _file_cache.get(path)
        if ent is None or ent[0] != st.st_mtime:
            with open(path) as f:
                rules = json.load(f).get("rules", [])
            _file_cache[path] = (st.st_mtime, rules)
            log.info("loaded %d rule(s) from %s" % (len(rules), path))
        return _file_cache[path][1]
    except FileNotFoundError:
        return []
    except Exception as e:
        log.warning("rules file error (%s); passthrough" % e)
        ent = _file_cache.get(path)
        return ent[1] if ent else []
