import json, logging, os, sys
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


def _log_identity(ctx):
    key = (ctx.get("client"), ctx.get("device_id"))
    if key in _seen:
        return
    _seen.add(key)
    # Show the values that a rule `match` must use. Put a rule after this.
    log.info("PlaybackInfo from %s" % engine.describe_ctx(ctx))


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

        rules = engine.load_rules(RULES_PATH)
        if not rules:
            return

        rule = engine.pick_rule(rules, ctx)
        if not rule:
            return
        dp = data.get("DeviceProfile")
        if not isinstance(dp, dict):
            return
        if not engine.apply_rule(rule, dp):
            return

        req.set_text(json.dumps(data))
        log.info("rewrote PlaybackInfo rule=%s (%s) client=%r"
                 % (rule.get("name", "?"), engine.describe_rule(rule), ctx.get("client")))
    except Exception as e:
        log.warning("addon error, passthrough: %s" % e)
        return
