import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "addon"))
import rules_engine as engine


def dp_basic():
    return {
        "DirectPlayProfiles": [{"Type": "Video", "AudioCodec": "aac,eac3"}],
        "TranscodingProfiles": [{"Type": "Video"}],
        "CodecProfiles": [],
    }


# --- value_matches: exact vs regex ---------------------------------------

def test_exact_match():
    assert engine.value_matches("Jellyfin for Android", "Jellyfin for Android")
    assert not engine.value_matches("Jellyfin for Android", "Jellyfin Android TV")

def test_regex_contains():
    assert engine.value_matches("/Android/", "Jellyfin for Android")
    assert engine.value_matches("/Android/", "Jellyfin Android TV")
    assert not engine.value_matches("/Android/", "Jellyfin Web")

def test_regex_flag_case_insensitive():
    assert engine.value_matches("/okhttp/i", "Jellyfin ... (OkHttp/4.12.0)")

def test_regex_anchor():
    assert engine.value_matches("/^abc/", "abc123")
    assert not engine.value_matches("/^abc/", "xabc123")

def test_none_value_never_matches():
    assert not engine.value_matches("x", None)

def test_bad_regex_does_not_match_or_crash():
    assert not engine.value_matches("/[/", "anything")


# --- auth parsing + ctx ---------------------------------------------------

def test_auth_fields():
    a = 'MediaBrowser Client="Jellyfin for Android", DeviceId="abc123", Version="2.7"'
    f = engine.auth_fields(a)
    assert f["Client"] == "Jellyfin for Android"
    assert f["DeviceId"] == "abc123"

def test_ctx_user_id_from_query_wins():
    ctx = engine.build_ctx('MediaBrowser Client="X"', "UA", "uid-query", {"UserId": "uid-body"})
    assert ctx["user_id"] == "uid-query"

def test_ctx_user_id_from_body_fallback():
    ctx = engine.build_ctx('MediaBrowser Client="X"', "UA", None, {"UserId": "uid-body"})
    assert ctx["user_id"] == "uid-body"


# --- rule_matches / pick_rule --------------------------------------------

def test_empty_match_matches_all():
    assert engine.rule_matches({}, {"client": "anything"})

def test_and_semantics():
    ctx = {"client": "Jellyfin Web", "user_id": "u1"}
    assert engine.rule_matches({"client": "Jellyfin Web", "user_id": "u1"}, ctx)
    assert not engine.rule_matches({"client": "Jellyfin Web", "user_id": "u2"}, ctx)

def test_missing_ctx_key_fails():
    assert not engine.rule_matches({"user_id": "u1"}, {"client": "X"})

def test_pick_first_match_wins():
    rules = [{"name": "a", "match": {"client": "/Android/"}},
             {"name": "b", "match": {}}]
    assert engine.pick_rule(rules, {"client": "Jellyfin for Android"})["name"] == "a"
    assert engine.pick_rule(rules, {"client": "Jellyfin Web"})["name"] == "b"

def test_pick_none_when_no_match():
    rules = [{"name": "a", "match": {"client": "Nope"}}]
    assert engine.pick_rule(rules, {"client": "Jellyfin Web"}) is None


# --- apply_rule: audio and video independent -----------------------------

def test_apply_audio_only():
    dp = dp_basic()
    assert engine.apply_rule({"max_audio_channels": 2}, dp) is True
    assert dp["DirectPlayProfiles"][0]["AudioCodec"] == "aac,mp3"
    assert dp["TranscodingProfiles"][0]["MaxAudioChannels"] == "2"
    assert any(c.get("Type") == "VideoAudio" for c in dp["CodecProfiles"])
    # video untouched
    assert "MaxStreamingBitrate" not in dp
    assert not any(c.get("Type") == "Video" for c in dp["CodecProfiles"])

def test_apply_video_only():
    dp = dp_basic()
    assert engine.apply_rule({"max_width": 1280, "max_bitrate": 6000000}, dp) is True
    assert dp["MaxStreamingBitrate"] == 6000000
    assert any(c.get("Type") == "Video" for c in dp["CodecProfiles"])
    # audio untouched
    assert dp["DirectPlayProfiles"][0]["AudioCodec"] == "aac,eac3"
    assert "MaxAudioChannels" not in dp["TranscodingProfiles"][0]
    assert not any(c.get("Type") == "VideoAudio" for c in dp["CodecProfiles"])

def test_apply_both():
    dp = dp_basic()
    assert engine.apply_rule({"max_audio_channels": 2, "max_width": 1920, "max_bitrate": 8000000}, dp)
    assert dp["MaxStreamingBitrate"] == 8000000
    assert any(c.get("Type") == "VideoAudio" for c in dp["CodecProfiles"])
    assert any(c.get("Type") == "Video" for c in dp["CodecProfiles"])

def test_apply_nothing_changes_nothing():
    dp = dp_basic()
    assert engine.apply_rule({"name": "noop", "match": {}}, dp) is False
    assert dp == dp_basic()

def test_apply_max_video_bit_depth():
    dp = {"DirectPlayProfiles": [{"Type": "Video", "VideoCodec": "h264,hevc", "AudioCodec": "aac"}],
          "TranscodingProfiles": [{"Type": "Video"}], "CodecProfiles": []}
    assert engine.apply_rule({"max_video_bit_depth": 8}, dp) is True
    conds = [c for v in dp["CodecProfiles"] if v.get("Type") == "Video" for c in v["Conditions"]]
    assert any(c.get("Property") == "VideoBitDepth" and c.get("Value") == "8" for c in conds)
    # audio and the direct-play video codec list are untouched
    assert dp["DirectPlayProfiles"][0]["AudioCodec"] == "aac"
    assert dp["DirectPlayProfiles"][0]["VideoCodec"] == "h264,hevc"

def test_apply_keep_video_codecs():
    dp = {"DirectPlayProfiles": [{"Type": "Video", "VideoCodec": "h264,hevc,av1", "AudioCodec": "aac,eac3"}],
          "TranscodingProfiles": [{"Type": "Video"}], "CodecProfiles": []}
    assert engine.apply_rule({"keep_video_codecs": "h264"}, dp) is True
    assert dp["DirectPlayProfiles"][0]["VideoCodec"] == "h264"
    # audio untouched
    assert dp["DirectPlayProfiles"][0]["AudioCodec"] == "aac,eac3"

def test_keep_video_codecs_ignores_entries_without_videocodec():
    dp = {"DirectPlayProfiles": [{"Type": "Video", "AudioCodec": "aac"}],
          "TranscodingProfiles": [], "CodecProfiles": []}
    engine.apply_rule({"keep_video_codecs": "h264"}, dp)
    assert "VideoCodec" not in dp["DirectPlayProfiles"][0]


# --- describe_ctx / describe_rule (log helpers) ---------------------------

def test_describe_ctx_shows_parsed_values():
    ctx = engine.build_ctx('MediaBrowser Client="Jellyfin for Android", DeviceId="abc"',
                           "UA", "uid-1", {})
    s = engine.describe_ctx(ctx)
    assert "client='Jellyfin for Android'" in s
    assert "device_id='abc'" in s
    assert "user_id='uid-1'" in s

def test_describe_ctx_shows_none_for_missing():
    ctx = engine.build_ctx("", "", None, {})
    assert "client=None" in engine.describe_ctx(ctx)

def test_describe_rule_lists_all_fields():
    rule = {"name": "r", "max_audio_channels": 2, "keep_audio_codecs": "aac",
            "max_width": 1344, "max_bitrate": 6000000,
            "keep_video_codecs": "h264", "max_video_bit_depth": 8}
    s = engine.describe_rule(rule)
    assert s == "maxch=2 keepac=aac maxw=1344 maxbr=6000000 keepvc=h264 maxbits=8"

def test_describe_rule_audio_default_keep():
    assert engine.describe_rule({"max_audio_channels": 2}) == "maxch=2 keepac=aac,mp3"

def test_describe_rule_only_present_fields():
    assert engine.describe_rule({"max_video_bit_depth": 8}) == "maxbits=8"

def test_describe_rule_empty_is_noop():
    assert engine.describe_rule({"name": "x", "match": {}}) == "no-op"


# --- load_rules -----------------------------------------------------------

def test_load_rules_missing(tmp_path):
    assert engine.load_rules(str(tmp_path / "nope.json")) == []

def test_load_rules_ok(tmp_path):
    p = tmp_path / "r.json"
    p.write_text('{"rules":[{"name":"x","match":{}}]}')
    rules = engine.load_rules(str(p))
    assert len(rules) == 1 and rules[0]["name"] == "x"

def test_load_rules_broken_json(tmp_path):
    p = tmp_path / "b.json"
    p.write_text("{not json")
    assert engine.load_rules(str(p)) == []
