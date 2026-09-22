# Contributing

Thanks for helping improve jellyfin-force-transcode.

## Project layout

- `addon/rules_engine.py` — pure logic (rule loading, matching, PlaybackInfo rewrite). No mitmproxy
  dependency, fully unit-tested.
- `addon/rewrite.py` — thin mitmproxy adapter that wires `rules_engine` into the request hook.
- `docker-entrypoint.sh` — builds the `mitmdump` command from environment variables.
- `tests/` — pytest.

## Run the tests

The logic and the tests need no third-party dependencies:

```bash
pip install pytest
pytest
```

## Build and run the image locally

```bash
docker build -t jellyfin-force-transcode .
docker run --rm -p 8097:8080 \
  -e JELLYFIN_URL=http://<your-jellyfin>:8096 \
  -v "$(pwd)/rules.json:/addon/rules.json:ro" \
  jellyfin-force-transcode
```

## Guidelines

- Add or adjust tests for any behaviour change.
- Keep the addon **fail-safe**: on any error, it must pass the request through unchanged.
- CI runs the tests first and only then builds the image — both must pass.
- Keep the addon dependency-free beyond mitmproxy (which the base image provides).
