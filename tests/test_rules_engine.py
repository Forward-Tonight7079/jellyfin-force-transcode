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

def test_auth_fields_decodes_plus_and_percent():
    # Real clients encode spaces. "+" and "%20" must decode to a space.
    a = 'MediaBrowser Client="Jellyfin+for+Android", Device="Jellyfin%20Media%20Player"'
    f = engine.auth_fields(a)
    assert f["Client"] == "Jellyfin for Android"
    assert f["Device"] == "Jellyfin Media Player"

def test_exact_client_match_after_decode():
    # The encoded header value must match the human-readable rule value.
    ctx = engine.build_ctx('MediaBrowser Client="Jellyfin+for+Android"', "UA", None, {})
    assert engine.value_matches("Jellyfin for Android", ctx["client"])

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


# --- schema: lists, normalize, deprecations ------------------------------

def test_codec_list_accepts_list_and_string():
    assert engine.codec_list(["AAC", " eac3 "]) == ["aac", "eac3"]
    assert engine.codec_list("aac, mp3") == ["aac", "mp3"]
    assert engine.codec_list(None) == [] and engine.codec_list("") == []

def test_normalize_grouped_has_no_notes():
    rule = {"name": "x", "match": {}, "audio": {"deny": ["opus"], "transcode_to": "aac"},
            "video": {"max_bit_depth": 8}, "max_bitrate": 6000000}
    spec, notes = engine.normalize(rule)
    assert notes == []
    assert spec["audio"]["deny"] == ["opus"] and spec["audio"]["transcode_to"] == ["aac"]
    assert spec["video"]["max_bit_depth"] == 8 and spec["max_bitrate"] == 6000000

def test_normalize_maps_every_deprecated_field():
    old = {"max_audio_channels": 2, "keep_audio_codecs": "aac", "transcode_audio_codec": "aac",
           "keep_video_codecs": "h264", "max_width": 1280, "max_video_bit_depth": 8}
    spec, notes = engine.normalize(old)
    assert len(notes) == 6 and all(n.startswith("deprecated field") for n in notes)
    assert "deprecated field max_video_bit_depth -> use video.max_bit_depth" in notes
    assert spec["audio"] == {"allow": ["aac"], "deny": [], "transcode_to": ["aac"], "max_channels": 2}
    assert spec["video"]["allow"] == ["h264"] and spec["video"]["max_width"] == 1280

def test_grouped_value_wins_over_deprecated():
    spec, _ = engine.normalize({"max_width": 1280, "video": {"max_width": 1920}})
    assert spec["video"]["max_width"] == 1920

def test_normalize_reports_unknown_fields():
    _, notes = engine.normalize({"max_bitrat": 1, "audio": {"denny": ["opus"]}})
    assert "unknown field max_bitrat (ignored)" in notes
    assert "unknown field audio.denny (ignored)" in notes

def test_rule_notes_once():
    rule = {"name": "once", "max_video_bit_depth": 8}
    assert engine.rule_notes_once(rule) != []
    assert engine.rule_notes_once(rule) == []


# --- apply_rule: legacy fields keep the 0.x result ------------------------

def test_legacy_audio_only():
    dp = dp_basic()
    assert engine.apply_rule({"max_audio_channels": 2}, dp) is True
    # legacy max_audio_channels alone still limits direct play to aac,mp3 (intersection)
    assert dp["DirectPlayProfiles"][0]["AudioCodec"] == "aac"
    assert dp["TranscodingProfiles"][0]["MaxAudioChannels"] == "2"
    assert any(c.get("Type") == "VideoAudio" for c in dp["CodecProfiles"])
    assert "MaxStreamingBitrate" not in dp
    assert not any(c.get("Type") == "Video" for c in dp["CodecProfiles"])

def test_legacy_equals_grouped():
    old = {"max_audio_channels": 2, "keep_audio_codecs": "aac,mp3", "max_width": 1344,
           "max_bitrate": 6000000, "max_video_bit_depth": 8}
    new = {"audio": {"max_channels": 2, "allow": ["aac", "mp3"]},
           "video": {"max_width": 1344, "max_bit_depth": 8}, "max_bitrate": 6000000}
    a, b = dp_lg_opus(), dp_lg_opus()
    engine.apply_rule(old, a); engine.apply_rule(new, b)
    assert a == b

def test_grouped_max_channels_has_no_implicit_allow():
    dp = dp_basic()
    engine.apply_rule({"audio": {"max_channels": 2}}, dp)
    assert dp["DirectPlayProfiles"][0]["AudioCodec"] == "aac,eac3"
    assert dp["TranscodingProfiles"][0]["MaxAudioChannels"] == "2"


# --- apply_rule: audio allow / deny / transcode_to ------------------------

def dp_lg_opus():
    # Shape of a TV profile that claims Opus for direct play and for transcode (copy).
    return {"DirectPlayProfiles": [{"Type": "Video", "Container": "mkv", "VideoCodec": "h264,hevc",
                                    "AudioCodec": "aac,ac3,eac3,opus"},
                                   {"Type": "Video", "Container": "webm"},
                                   {"Type": "Audio", "Container": "opus"}],
            "TranscodingProfiles": [{"Type": "Video", "Container": "mp4", "VideoCodec": "h264,hevc",
                                     "AudioCodec": "opus,aac,ac3,eac3"},
                                    {"Type": "Audio", "Container": "opus", "AudioCodec": "opus"}],
            "CodecProfiles": []}

def test_lg_opus_case_one_line():
    # Real case: an LG TV claims Opus but stutters. One field fixes it.
    dp = dp_lg_opus()
    assert engine.apply_rule({"audio": {"deny": ["opus"]}}, dp) is True
    assert dp["DirectPlayProfiles"][0]["AudioCodec"] == "aac,ac3,eac3"
    # no copy of Opus in a remux
    assert dp["TranscodingProfiles"][0]["AudioCodec"] == "aac,ac3,eac3"
    # the open webm entry (no list = any codec) gets a never-true codec profile for opus
    cp = [c for c in dp["CodecProfiles"] if c["Type"] == "VideoAudio"]
    assert len(cp) == 1 and cp[0]["Codec"] == "opus"
    assert cp[0]["Conditions"][0]["Value"] == "0" and cp[0]["Conditions"][0]["IsRequired"]
    # music profiles, channels and video untouched
    assert "AudioCodec" not in dp["DirectPlayProfiles"][2]
    assert dp["TranscodingProfiles"][1]["AudioCodec"] == "opus"
    assert "MaxAudioChannels" not in dp["TranscodingProfiles"][0]
    assert dp["DirectPlayProfiles"][0]["VideoCodec"] == "h264,hevc"
    assert "MaxStreamingBitrate" not in dp

def test_audio_transcode_to():
    dp = dp_lg_opus()
    engine.apply_rule({"audio": {"deny": "opus", "transcode_to": "eac3"}}, dp)
    assert dp["TranscodingProfiles"][0]["AudioCodec"] == "eac3"

def test_audio_allow_intersects_and_fills_open_entries():
    dp = dp_lg_opus()
    engine.apply_rule({"audio": {"allow": ["aac", "mp3"]}}, dp)
    assert dp["DirectPlayProfiles"][0]["AudioCodec"] == "aac"       # mp3 not claimed by client
    assert dp["DirectPlayProfiles"][1]["AudioCodec"] == "aac,mp3"   # open entry gets the list
    assert dp["TranscodingProfiles"][0]["AudioCodec"] == "aac"
    assert not any(c["Type"] == "VideoAudio" for c in dp["CodecProfiles"])

def test_allow_and_deny_together():
    dp = dp_lg_opus()
    engine.apply_rule({"audio": {"allow": ["aac", "eac3", "opus"], "deny": ["opus"]}}, dp)
    assert dp["DirectPlayProfiles"][0]["AudioCodec"] == "aac,eac3"
    assert dp["TranscodingProfiles"][0]["AudioCodec"] == "aac,eac3"

def test_transcode_list_falls_back_when_everything_denied():
    dp = {"DirectPlayProfiles": [], "CodecProfiles": [],
          "TranscodingProfiles": [{"Type": "Video", "AudioCodec": "opus"}]}
    engine.apply_rule({"audio": {"deny": ["opus"]}}, dp)
    assert dp["TranscodingProfiles"][0]["AudioCodec"] == "aac"


# --- apply_rule: video ----------------------------------------------------

def test_fire_tablet_10bit_case():
    # Real case: a Fire tablet direct-plays 8-bit HEVC but fails on 10-bit.
    dp = dp_lg_opus()
    assert engine.apply_rule({"video": {"max_bit_depth": 8}}, dp) is True
    conds = [c for v in dp["CodecProfiles"] if v.get("Type") == "Video" for c in v["Conditions"]]
    assert any(c.get("Property") == "VideoBitDepth" and c.get("Value") == "8" for c in conds)
    assert dp["DirectPlayProfiles"][0]["VideoCodec"] == "h264,hevc"
    assert dp["DirectPlayProfiles"][0]["AudioCodec"] == "aac,ac3,eac3,opus"

def test_video_deny_blocks_direct_play_and_copy():
    dp = dp_lg_opus()
    engine.apply_rule({"video": {"deny": ["hevc"]}}, dp)
    assert dp["DirectPlayProfiles"][0]["VideoCodec"] == "h264"
    assert dp["TranscodingProfiles"][0]["VideoCodec"] == "h264"
    assert any(c["Type"] == "Video" and c["Codec"] == "hevc" for c in dp["CodecProfiles"])

def test_video_allow():
    dp = dp_lg_opus()
    engine.apply_rule({"video": {"allow": "h264"}}, dp)
    assert dp["DirectPlayProfiles"][0]["VideoCodec"] == "h264"
    assert dp["DirectPlayProfiles"][1]["VideoCodec"] == "h264"
    assert dp["TranscodingProfiles"][0]["VideoCodec"] == "h264"
    assert dp["DirectPlayProfiles"][0]["AudioCodec"] == "aac,ac3,eac3,opus"

def test_video_width_and_bitrate():
    dp = dp_basic()
    assert engine.apply_rule({"video": {"max_width": 1280}, "max_bitrate": 6000000}, dp) is True
    assert dp["MaxStreamingBitrate"] == 6000000
    assert any(c.get("Type") == "Video" for c in dp["CodecProfiles"])
    assert dp["DirectPlayProfiles"][0]["AudioCodec"] == "aac,eac3"
    assert "MaxAudioChannels" not in dp["TranscodingProfiles"][0]

def test_apply_nothing_changes_nothing():
    dp = dp_basic()
    assert engine.apply_rule({"name": "noop", "match": {}}, dp) is False
    assert engine.apply_rule({"audio": {}, "video": {}}, dp) is False
    assert dp == dp_basic()


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

def test_describe_rule_grouped():
    rule = {"audio": {"deny": ["opus"], "transcode_to": "aac"},
            "video": {"max_bit_depth": 8}, "max_bitrate": 6000000}
    assert engine.describe_rule(rule) == \
        "audio(deny=opus transcode_to=aac) video(max_bit_depth=8) max_bitrate=6000000"

def test_describe_rule_legacy_in_new_spelling():
    assert engine.describe_rule({"max_audio_channels": 2}) == "audio(allow=aac,mp3 max_channels=2)"

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

def test_load_rules_logs_each_state_once(tmp_path, caplog):
    import logging, os
    caplog.set_level(logging.INFO, logger="force-transcode")
    p = tmp_path / "r.json"
    engine.load_rules(str(p))
    engine.load_rules(str(p))
    assert sum("no rules file" in m for m in caplog.messages) == 1
    p.write_text('{"rules":[{"name":"a"},{"name":"b"}]}')
    engine.load_rules(str(p)); engine.load_rules(str(p))
    assert sum("loaded 2 rule(s)" in m and ": a, b" in m for m in caplog.messages) == 1

def test_load_rules_error_keeps_previous_and_logs_once(tmp_path, caplog):
    import logging, os
    caplog.set_level(logging.INFO, logger="force-transcode")
    p = tmp_path / "r.json"
    p.write_text('{"rules":[{"name":"a"}]}')
    assert len(engine.load_rules(str(p))) == 1
    p.write_text('{"rules":[{"name":"a"},]}')
    os.utime(p, (1, 1))   # make sure the mtime changes
    for _ in range(3):
        assert [r["name"] for r in engine.load_rules(str(p))] == ["a"]
    errs = [m for m in caplog.messages if "rules file error" in m]
    assert len(errs) == 1 and "keeping the previous 1 rule(s)" in errs[0]

def test_load_rules_rules_not_a_list(tmp_path):
    p = tmp_path / "r.json"
    p.write_text('{"rules":{"name":"a"}}')
    assert engine.load_rules(str(p)) == []


# --- describe_outcome (Jellyfin decision) ----------------------------------

def _resp(url=None, dp=False, ds=False):
    ms = {"SupportsDirectPlay": dp, "SupportsDirectStream": ds}
    if url:
        ms["TranscodingUrl"] = url
    return {"MediaSources": [ms]}

def test_outcome_direct_play():
    assert engine.describe_outcome(_resp(dp=True)) == "direct play"

def test_outcome_audio_only_transcode():
    url = ("/videos/x/master.m3u8?VideoCodec=h264,hevc,av1&AudioCodec=aac,ac3,eac3"
           "&TranscodeReasons=AudioCodecNotSupported")
    assert engine.describe_outcome(_resp(url)) == \
        "transcode: video copied, audio -> aac (AudioCodecNotSupported)"

def test_outcome_video_and_stereo():
    url = ("/videos/x/master.m3u8?VideoCodec=h264&AudioCodec=aac&TranscodingMaxAudioChannels=2"
           "&TranscodeReasons=VideoBitDepthNotSupported%2CAudioChannelsNotSupported")
    assert engine.describe_outcome(_resp(url)) == \
        "transcode: video -> h264, audio -> aac 2ch (VideoBitDepthNotSupported, AudioChannelsNotSupported)"

def test_outcome_bitrate_is_video():
    url = "/x?VideoCodec=h264&AudioCodec=aac&TranscodeReasons=ContainerBitrateExceedsLimit"
    assert engine.describe_outcome(_resp(url)) == \
        "transcode: video -> h264, audio copied (ContainerBitrateExceedsLimit)"

def test_outcome_remux_and_errors():
    assert engine.describe_outcome(_resp("/x?VideoCodec=h264")) == "remux (video and audio copied)"
    assert engine.describe_outcome({"ErrorCode": "NoCompatibleStream"}) == "error NoCompatibleStream"
    assert engine.describe_outcome({"MediaSources": []}) is None
    assert engine.describe_outcome("junk") is None
