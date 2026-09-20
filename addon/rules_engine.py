"""Pure rules/matching/rewrite logic for jellyfin-force-transcode.

No mitmproxy dependency, so it is unit-testable with plain Python. rewrite.py is
a thin mitmproxy adapter around these functions.
"""
import json, logging, os, re

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
    return dict(re.findall(r'(\w+)="([^"]*)"', auth or ""))


def build_ctx(auth, user_agent, query_user_id, body):
    uid = query_user_id
    if uid is None and isinstance(body, dict):
        uid = body.get("UserId")
    f = auth_fields(auth)
    return {"client": f.get("Client"), "device_id": f.get("DeviceId"),
            "user_agent": user_agent or "", "user_id": uid}


# --- rewrite --------------------------------------------------------------

def _codec_profiles(dp):
    cps = dp.get("CodecProfiles")
    if not isinstance(cps, list):
        cps = []; dp["CodecProfiles"] = cps
    return cps


def apply_rule(rule, dp):
    """Mutate a DeviceProfile in place per the rule. Returns True if changed."""
    changed = False

    ch = rule.get("max_audio_channels")
    if ch is not None:
        ch = str(ch)
        keep = rule.get("keep_audio_codecs", "aac,mp3")
        for d in (dp.get("DirectPlayProfiles") or []):
            if d.get("Type") == "Video" and d.get("AudioCodec"):
                d["AudioCodec"] = keep
        for tp in (dp.get("TranscodingProfiles") or []):
            if tp.get("Type") == "Video":
                tp["MaxAudioChannels"] = ch
        _codec_profiles(dp).append(
            {"Type": "VideoAudio",
             "Codec": "aac,ac3,eac3,dts,truehd,mp3,flac,opus,vorbis,dca",
             "Conditions": [{"Condition": "LessThanEqual", "Property": "AudioChannels",
                             "Value": ch, "IsRequired": True}]})
        changed = True

    mw = rule.get("max_width")
    if isinstance(mw, int):
        _codec_profiles(dp).append(
            {"Type": "Video", "Codec": "h264,hevc,mpeg4,vp9,av1,vc1",
             "Conditions": [{"Condition": "LessThanEqual", "Property": "Width",
                             "Value": str(mw), "IsRequired": True}]})
        changed = True

    if isinstance(rule.get("max_bitrate"), int):
        dp["MaxStreamingBitrate"] = rule["max_bitrate"]
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
