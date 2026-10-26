import asyncio, json, logging, os, sys, threading, time, urllib.request
from mitmproxy import http

# Make sibling modules importable when loaded by mitmdump (-s /addon/rewrite.py).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules_engine as engine

RULES_PATH = os.environ.get("RULES_FILE", "/addon/rules.json")
JELLYFIN_URL = os.environ.get("JELLYFIN_URL", "").rstrip("/")
# Proxies whose X-Forwarded-For / X-Real-IP the proxy believes (comma list of IPs or networks).
TRUSTED_PROXIES = os.environ.get("TRUSTED_PROXIES", engine.DEFAULT_TRUSTED)
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

# Remember which identities we logged, so we print each identity only one time.
_seen = set()
WATCH_SECONDS = 2
USER_TTL = 3600       # seconds to remember token -> user
USER_FAIL_TTL = 60    # seconds to remember a failed lookup


def _log_identity(ctx):
    key = (ctx.get("client"), ctx.get("device_id"), ctx.get("user_id"), ctx.get("ip"))
    if key in _seen:
        return
    _seen.add(key)
    # Show the values that a rule `match` must use. Put a rule after this.
    log.info("PlaybackInfo from %s" % engine.describe_ctx(ctx))


def _refresh():
    """Load the config (cached by mtime) and warn about deprecated or unknown fields."""
    cfg = engine.load_config(RULES_PATH)
    for r in cfg["rules"]:
        if isinstance(r, dict):
            for note in engine.rule_notes_once(r):
                log.warning("rule=%s: %s" % (r.get("name", "?"), note))
    return cfg


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


# --- user from token --------------------------------------------------------
# The apps (jellyfin-sdk-kotlin) do not send the user id in PlaybackInfo. The token
# does identify the user, so ask Jellyfin who owns it. The request uses the client's
# own auth headers without a change, so Jellyfin records nothing new.

_users = {}  # token -> (expires, user_id, user_name)
_AUTH_HEADERS = ("Authorization", "X-Emby-Authorization", "X-Emby-Token", "X-MediaBrowser-Token")


def _token_and_headers(req):
    headers = {h: req.headers[h] for h in _AUTH_HEADERS if req.headers.get(h)}
    auth = " ".join(headers.get(h, "") for h in ("Authorization", "X-Emby-Authorization"))
    token = engine.auth_fields(auth).get("Token") or headers.get("X-Emby-Token") \
        or headers.get("X-MediaBrowser-Token")
    if not token:
        token = req.query.get("api_key") or req.query.get("ApiKey")
        if token:
            headers["X-Emby-Token"] = token
    return token, headers


def _fetch_user(headers):
    r = urllib.request.Request(JELLYFIN_URL + "/Users/Me", headers=headers)
    with urllib.request.urlopen(r, timeout=3) as resp:
        u = json.load(resp)
    return engine._norm_id(u.get("Id")), u.get("Name")


async def _user_for(req):
    token, headers = _token_and_headers(req)
    if not token or not JELLYFIN_URL:
        return None, None
    now = time.time()
    hit = _users.get(token)
    if hit and hit[0] > now:
        return hit[1], hit[2]
    try:
        uid, name = await asyncio.to_thread(_fetch_user, headers)
        _users[token] = (now + USER_TTL, uid, name)
    except Exception:
        # An API key has no user, or Jellyfin is slow: no user, try again later.
        uid, name = None, None
        _users[token] = (now + USER_FAIL_TTL, None, None)
    return uid, name


# --- hooks ------------------------------------------------------------------

async def request(flow: http.HTTPFlow) -> None:
    try:
        req = flow.request
        if req.method != "POST" or "/PlaybackInfo" not in req.path:
            return

        data = json.loads(req.get_text() or "{}")
        auth = req.headers.get("Authorization", "") + " " + req.headers.get("X-Emby-Authorization", "")
        uid = req.query.get("userId") or req.query.get("UserId")
        peer = flow.client_conn.peername[0] if flow.client_conn.peername else None
        ip = engine.client_ip(peer, req.headers.get("X-Forwarded-For"),
                              req.headers.get("X-Real-IP"), TRUSTED_PROXIES)
        ctx = engine.build_ctx(auth, req.headers.get("User-Agent", ""), uid, data, ip=ip)
        tuid, tname = await _user_for(req)
        if tuid:
            ctx["user_id"], ctx["user"] = tuid, tname

        cfg = _refresh()
        ctx["device"] = engine.resolve_device(cfg["devices"], ctx)
        _log_identity(ctx)
        # The response hook writes one result line for each PlaybackInfo.
        flow.metadata["jft"] = {"who": "device=%s user=%r client=%r"
                                       % (ctx["device"] or "unknown", ctx["user"], ctx["client"]),
                                "rule": "none"}

        rule = engine.pick_rule(cfg["rules"], ctx)
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
        log.info("playback %s rule=%s -> %s" % (meta["who"], meta["rule"], result))
    except Exception as e:
        log.warning("could not read the Jellyfin answer: %s" % e)


def error(flow: http.HTTPFlow) -> None:
    meta = flow.metadata.get("jft")
    if meta:
        log.warning("playback %s rule=%s -> no answer from Jellyfin (%s)"
                    % (meta["who"], meta["rule"], flow.error))
