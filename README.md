# LoadForge

LoadForge is a DSL and runtime for describing and executing API tests under load.
The goal is to avoid per-test scripting and instead declare everything in a `.lf` file:

- environment and target
- authentication
- scenarios and response validations
- load profile
- SLO/metrics checks

## Problem This Project Solves

In classic load testing setups, logic is spread across scripts, helpers, and config files. That usually leads to:

- slower test authoring and updates
- lower readability
- harder reviews and reuse
- weak traceability between "what we test" and "how runtime executes it"

LoadForge introduces a single DSL for test intent, while the runtime handles execution, measurement, and reporting.

## How It Solves It

1. DSL (`.lf`) is parsed with TextX grammar (`src/loadforge/grammar/loadforge.tx`).
2. Parse output is mapped to typed Python models (`src/loadforge/model`).
3. Preprocessors normalize values (for example HTTP methods and JSON check kind to enum values).
4. Runtime prepares context (env + vars), optionally runs auth login, then executes scenarios.
5. Every request is measured and recorded (latency, status, success/error).
6. Runtime computes aggregates (p50/p95/p99, errorRate, rps) and evaluates metric thresholds.
7. If stopped early, runtime still prints partial metrics collected so far.

## DSL Proposal (Current Shape)

Core blocks:

- `test`
- `environment`
- `target`
- `auth login`
- `variables`
- `scenario` (`request`, `expect status`, `expect json`)
- `load`
- `metrics`

### Authentication Modes

`auth login` supports two execution modes:

- Shared token auth (no `file` flag): one login request is executed, and the same Bearer token is reused by all virtual users.
- Per-user auth (`file` flag present): each virtual user authenticates individually using credentials from an external `.ulf` (User List File) provided via the CLI.

The `file` keyword in the auth block is a boolean flag — it signals that a `.ulf` file is required. The actual path to the `.ulf` file is provided as a CLI argument (the same way `.env` is provided):

```
loadforge test.lf .env users.ulf
```

`.ulf` (User List File) format uses a simple `username : password` syntax, one entry per line, parsed by textX:

```
alice@example.com : secret123
bob@example.com : hunter2
charlie@example.com : pa$$w0rd
```

`.ulf` mode details:

- The `file` flag in `auth login {}` declares that the test requires a `.ulf` file.
- The `.ulf` file path is provided as the third positional CLI argument (after `.lf` and `.env`).
- Use `--info` to print JSON metadata for a `.lf` file, including `env`, `userlist`, and `name`.
- Auth `body` fields use `${username}` and `${password}` interpolation from `.ulf` entries.
- If `load.users` is greater than the number of `.ulf` entries, users are assigned in round-robin order.

### Environment, Variables, and References

`environment` reads system variables via `env("KEY")`:

```lf
environment {
  baseUrl = env("BASE_URL")
  token = env("TOKEN")
}
```

`variables` defines local DSL variables:

```lf
variables {
  q = "phone"
  pageSize = "20"
}
```

References use `#name` and can point to env values or variables:

```lf
target #baseUrl

variables {
  authHeader = #token
}
```

String interpolation is supported with `${name}`:

```lf
request GET "/catalog/search?q=${q}&limit=${pageSize}"
```

Context resolution order:

- load `environment` first
- then resolve `variables` (variables can reference env values)
- runtime builds a unified context; duplicate names are not allowed

### Example: Functional Test

```lf
test "Functional Test Demo" {
  environment {
    baseUrl = env("BASE_URL")
  }

  target #baseUrl

  scenario "fetch index" {
    request GET "/"
    expect status 200
  }
}
```

### Example: Load + Metric Thresholds

```lf
test "Catalog search - steady load" {
  environment {
    baseUrl = env("BASE_URL")
  }

  target #baseUrl

  scenario "search" {
    request GET "/catalog/search?q=phone"
    expect status 200
    expect json $.results isArray
  }

  load {
    users 50
    rampUp 30s
    duration 5m
  }

  metrics {
    p95 < 250ms
    errorRate < 1%
  }
}
```

## JSON Check Types

`expect json` uses JSONPath and supports:

- `isArray`
- `notEmpty`
- `isEmpty`
- `equals <value|#ref>`
- `hasSize <number>`
- `isNull`
- `notNull`
- `isObject`
- `isString`
- `isNumber`
- `isBool`
- `contains <value|#ref>`
- `matches <regex|#ref>`

Example:

```lf
scenario "json checks" {
  request GET "/users/1"
  expect status 200
  expect json $.id notNull
  expect json $.name isString
  expect json $.tags isArray
  expect json $.tags notEmpty
  expect json $.email matches "[^@]+@[^@]+"
}
```

## Parsing Output

Parser returns a `TestFile` model with nested dataclass objects.
Conceptually:

```text
TestFile
  -> Test(name, environment, target, auth, variables, scenarios, load, metrics)
      -> Scenario(name, steps=[Request | ExpectStatus | ExpectJson, ...])
      -> Load(users, ramp_up, duration)
      -> MetricsBlock(checks=[MetricExpectation, ...])
```

## How Interpretation Works

Runtime flow:

1. `parse_file` loads DSL and creates model.
2. `run_test` resolves env/vars/target.
3. If `auth login` exists:
   - shared mode authenticates once before load and reuses one Bearer token;
   - `.ulf` mode authenticates each virtual user with credentials from an external `.ulf` file.
4. `run_load_test_async` starts virtual users with ramp-up behavior.
5. Every `request` is sent via `httpx` and `asyncio`, latency is measured, and data is recorded into `MetricsCollector`.
6. `expect` steps validate the last response; failures mark the last request as failed.
7. Runtime builds final report (`LoadTestResult`) with throughput, latency, errors, and per-scenario stats.

## CLI Output Examples

### While test is running (live progress line)

In load mode, CLI renders a single updating line with elapsed time, active users, request count, throughput, and errors:

```text
⠹   6.0s / 30s │ Users: 10/10 │ Reqs: 666 │ Req/s: 107.3 │ Errors: 0
```

This line refreshes in place until the test ends or is stopped.

### Final report (after completion)

After execution, CLI prints a report like:

```text
LoadForge Load Test Report
Test: Load + Metrics Demo
Duration: 10.0s | Users: 10 | Ramp-up: 3s

Throughput:
  Total requests: 10,545
  Requests/sec:   1053.7

Latency (ms):
  Min: 0.8      Avg: 8.0      p50: 3.9
  p95: 12.9     p99: 18.0     Max: 2959.9

Errors:
  Error rate: 0.0% (0/10,545)

Per-scenario breakdown:
  fetch index  reqs: 10,545  rps: 1053.7  p95: 12.9ms  err: 0.0%

Metric thresholds:  PASS

Result: PASS
```

If stopped early, report includes `Stopped early` and still shows partial metrics collected so far.

## Next

- For setup, commands, testing, and debugging see [development.md](development.md).
- DSL examples are in `examples/` (see `examples/README.md`).
- Use `examples/.env.example` as a template for `examples/.env`.

## VS Code Extension

There is a VS Code extension for this project that provides:

- syntax highlighting for `.lf` files
- bundled executable/runtime integration
- running tests directly from VS Code

Extension link: [link](https://github.com/BulatovicBalsa/vscode-loadforge)
