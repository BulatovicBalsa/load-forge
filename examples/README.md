# Examples

This folder contains practical `.lf` examples from minimal to full-featured.

## Files

- `functional_demo.lf`: minimal functional smoke test (`GET /`, status 200)
- `load_demo.lf`: minimal load test with `users/rampUp/duration`
- `demo_metrics.lf`: load test plus metrics thresholds (`p95`, `errorRate`)
- `expect_json_demo.lf`: JSONPath assertions and all supported JSON check types
- `demo.lf`: full scenario with env references, auth login, variables/interpolation, load, and metrics

## Environment

Use `examples/.env.example` as a template, then create/update `examples/.env`.

```bash
cp examples/.env.example examples/.env
```

## Quick start

```bash
# Terminal 1
python -m http.server 9999

# Terminal 2
uv run loadforge examples/functional_demo.lf examples/.env
uv run loadforge examples/load_demo.lf examples/.env
uv run loadforge examples/demo_metrics.lf examples/.env
```

Note: `expect_json_demo.lf` and `demo.lf` assume an API with matching endpoints/payloads.

## Run Mock API For All Examples

`mock_api.py` is a FastAPI app designed to satisfy all example files.

```bash
# Terminal 1
uv run --with fastapi --with uvicorn uvicorn examples.mock_api:app --host 127.0.0.1 --port 9999

# Terminal 2
uv run loadforge examples/functional_demo.lf examples/.env
uv run loadforge examples/load_demo.lf examples/.env
uv run loadforge examples/demo_metrics.lf examples/.env
uv run loadforge examples/expect_json_demo.lf examples/.env
uv run loadforge examples/demo.lf examples/.env
```
