import json, logging, os, sys, threading, time
from mitmproxy import http

# Make sibling modules importable when loaded by mitmdump (-s /addon/rewrite.py).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules_engine as engine

RULES_PATH = os.environ.get("RULES_FILE", "/addon/rules.json")
LOG_MODE = os.environ.get("LOG", "events").strip().lower()
if LOG_MODE not in ("full", "events", "quiet"):
    LOG_MODE = "events"

# Logging modes (see README):
#   full   - mitmproxy shows every request; it also displays this logger. Verbose.
#   events - entrypoint silences mitmproxy (flow_detail=0); we attach our own
#            stdout handler so only meaningful events/warnings are printed.
#   quiet  - suppress this addon's output entirely.
log = logging.getLogger("force-transcode")
if LOG_MODE == "events":
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("jft: %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False
elif LOG_MODE == "quiet":
    log.setLevel(logging.CRITICAL + 1)
    log.propagate = False

# Remember which identities we logged, so we print each client only one time.
_seen = set()
WATCH_SECONDS = 2


def _log_identity(ctx):
    key = (ctx.get("client"), ctx.get("device_id"))
    if key in _seen:
        return
    _seen.add(key)
    # Show the values that a rule `match` must use. Put a rule after this.
    log.info("PlaybackInfo from %s" % engine.describe_ctx(ctx))


def _refresh():
    """Load the rules (cached by mtime) and warn about deprecated or unknown fields."""
    rules = engine.load_rules(RULES_PATH)
    for r in rules:
        if isinstance(r, dict):
            for note in engine.rule_notes_once(r):
                log.warning("rule=%s: %s" % (r.get("name", "?"), note))
    return rules


def _watch():
    # Re-check the rules file, so a saved change (or a typing error) shows in the
    # log at once, not at the next playback.
    while True:
        time.sleep(WATCH_SECONDS)
        try:
            _refresh()
        except Exception as e:
            log.warning("rules watch error: %s" % e)


def running():
    _refresh()
    threading.Thread(target=_watch, name="jft-rules-watch", daemon=True).start()


def request(flow: http.HTTPFlow) -> None:
    try:
        req = flow.request
        if req.method != "POST" or "/PlaybackInfo" not in req.path:
            return

        data = json.loads(req.get_text() or "{}")
        auth = req.headers.get("Authorization", "") + " " + req.headers.get("X-Emby-Authorization", "")
        uid = req.query.get("userId") or req.query.get("UserId")
        ctx = engine.build_ctx(auth, req.headers.get("User-Agent", ""), uid, data)
        _log_identity(ctx)
        # The response hook writes one result line for each PlaybackInfo.
        flow.metadata["jft"] = {"client": ctx.get("client"), "rule": "none"}

        rule = engine.pick_rule(_refresh(), ctx)
        if not rule:
            return
        flow.metadata["jft"]["rule"] = "%s (no-op)" % rule.get("name", "?")
        dp = data.get("DeviceProfile")
        if not isinstance(dp, dict):
            return
        if not engine.apply_rule(rule, dp):
            return

        req.set_text(json.dumps(data))
        flow.metadata["jft"]["rule"] = "%s %s" % (rule.get("name", "?"), engine.describe_rule(rule))
    except Exception as e:
        log.warning("addon error, passthrough: %s" % e)
        return


def response(flow: http.HTTPFlow) -> None:
    meta = flow.metadata.get("jft")
    if not meta:
        return
    try:
        if flow.response.status_code != 200:
            result = "Jellyfin answered HTTP %d" % flow.response.status_code
        else:
            result = engine.describe_outcome(json.loads(flow.response.get_text() or "{}")) or "unknown"
        log.info("playback client=%r rule=%s -> %s" % (meta["client"], meta["rule"], result))
    except Exception as e:
        log.warning("could not read the Jellyfin answer: %s" % e)


def error(flow: http.HTTPFlow) -> None:
    meta = flow.metadata.get("jft")
    if meta:
        log.warning("playback client=%r rule=%s -> no answer from Jellyfin (%s)"
                    % (meta["client"], meta["rule"], flow.error))
