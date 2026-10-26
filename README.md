# retrypace

Only omitting `--config` selects defaults. An explicitly empty path (`--config ""` or `--config=`), including an empty shell-variable expansion, is an unreadable configuration: exit 1 with no report. Strategy overrides and pressure gates do not bypass this validation.

**A small, offline retry-schedule auditor for design reviews and CI.**

Given a retry policy and a fleet of clients, retrypace answers:

- How many complete attempts fit each client's deadline?
- How many requests can overlap, including retries that cross bucket boundaries?
- How large is the worst sliding-window burst, and how much pressure exceeds a reference concurrency limit?
- Does a proposed policy violate your explicit pressure gates?

It is a deterministic Python library and CLI, with no runtime dependencies, network traffic, telemetry, or actual sleeping. Python 3.10+ is required.

[中文](docs/zh-CN.md) · [Русский](docs/ru.md) · [Deutsch](docs/de.md) · [Model and report reference](docs/model.md)

## Quick start

From a source checkout:

```sh
git clone https://github.com/loufengzh/retrypace.git
cd retrypace
python -m retrypace --config examples/burst.json --compare
python -m retrypace --config examples/staggered.json --format csv > attempts.csv
python -m unittest discover -s tests -v
```

No installation is needed. Optional local installation: `python -m pip install .` exposes the `retrypace` command; the build backend may need downloading. This project is not currently published to PyPI, so do not assume that an identically named registry package is this project.

## A useful, deliberately narrow model

Every admitted attempt fails and consumes a fixed duration. Each client retries sequentially. A request is admitted only when its **entire duration fits its relative deadline**. Backoff starts after the failed attempt ends. This is a pressure envelope for a prescribed all-failure scenario, not a prediction of recovery or a universal worst case under arbitrary real-world failures.

The `concurrency_limit` is an observation threshold, not an enforced semaphore. Nothing is queued, dropped, or throttled by it. Initial requests are included in totals and also separated from retry-only peaks.

## Example: jitter is not a universal improvement

For `examples/burst.json` (100 clients, 40 ms attempts, 1,800 ms per-client deadline, seed 42), the implementation produces:

| Strategy | Attempts | Deadline-stopped clients | Retry peak concurrency | Retry peak starts / 100 ms |
| --- | ---: | ---: | ---: | ---: |
| fixed | 600 | 0 | 100 | 100 |
| exponential | 500 | 100 | 100 | 100 |
| full-jitter | 578 | 22 | 51 | 109 |
| equal-jitter | 504 | 96 | 84 | 100 |
| decorrelated | 469 | 72 | 25 | 61 |

All strategies retain the 100-request initial concurrency spike. In this scenario full jitter reduces retry overlap but increases retry starts in the busiest 100 ms window. Shorter waits can fit more retries into the deadline. These are different metrics: choose gates that reflect your bottleneck. A single seed is not statistical evidence that one strategy always wins.

## Configuration

All times are integer milliseconds. JSON may specify any subset; omitted fields use these defaults. Unknown keys and invalid types are errors, including booleans in numeric fields.

`--config` accepts a UTF-8 JSON object without a BOM, at most 64 KiB (65,536 bytes), including whitespace. Duplicate JSON keys are rejected, even if their values match or their spellings use different JSON escapes; there is no last-key-wins behavior. NaN and Infinity are rejected. Invalid, oversized or excessively nested input exits 1 with no report, before strategy overrides or CI gates are applied. The byte limit applies to CLI file loading; `Config.from_dict` validates an already parsed mapping and cannot detect duplicate keys lost by another JSON loader.

```json
{
  "clients": 100,
  "max_attempts": 5,
  "base_ms": 100,
  "cap_ms": 2000,
  "attempt_ms": 50,
  "deadline_ms": 3000,
  "stagger_ms": 0,
  "window_ms": 100,
  "concurrency_limit": 20,
  "seed": 1,
  "strategy": "full-jitter"
}
```

- `max_attempts` includes the initial request, not just retries.
- Client `i` starts at `i × stagger_ms`; its deadline is relative to that start.
- `deadline_ms: 0` is valid and admits no request.
- `cap_ms >= base_ms`; all other numeric fields except deadline, stagger and seed must be positive.
- Seed accepts unsigned 32-bit integers, including zero. Other fields are at most 1,000,000,000.
- `clients × max_attempts <= 1,000,000` bounds work. Reports with this many events can still use substantial memory; start small.
- Strategies: `fixed`, `exponential`, `full-jitter`, `equal-jitter`, `decorrelated`.

## CLI and CI gates

```sh
# Stable, sorted-key JSON; omit event detail for smaller output.
python -m retrypace --config examples/burst.json --summary-only > report.json

# Override a configuration's strategy.
python -m retrypace --config examples/burst.json --strategy exponential

# Compare all five strategies under the same inputs and seed.
python -m retrypace --config examples/burst.json --compare > comparison.json

# Emits the report even when a threshold is exceeded.
python -m retrypace --config examples/staggered.json \
  --max-peak-concurrency 50 --max-window-starts 200 > report.json
```

Gates inspect **all attempts**, including initial requests. Equality passes; a strictly higher value fails. With `--compare`, any failing strategy fails the command. Use the library for custom retry-only gates. CSV exports per-attempt `client,attempt,start_ms,end_ms`; it cannot be combined with `--compare` or `--summary-only`.

Exit status: `0` success, `1` unreadable/invalid configuration, `2` exceeded gate or CLI usage error. Gate failures preserve machine-readable stdout; diagnostics go to stderr. `--help` and `--version` are available.

## Library

```python
from retrypace import Config, compare, simulate

config = Config(clients=30, max_attempts=4, deadline_ms=1000, seed=42)
report = simulate(config)
assert report["summary"]["max_client_elapsed_ms"] <= config.deadline_ms
print(report["summary"]["retry_peak_concurrency"])
policies = compare(config)  # strategy -> report, without per-attempt events
```

`Config` is an immutable validated dataclass. `Config.from_dict(mapping)` validates JSON-like input. `simulate(config, include_events=False)` omits events from output, but still computes the whole schedule in memory. Reports contain `schema_version`, `model`, `config`, `summary`, `buckets`, and optionally `events`. See [exact semantics](docs/model.md).

## Related work and originality

[Retry Lab](https://github.com/kyan9400/retry-lab) is an interactive browser simulator of shared outages and constrained recovery capacity. retrypace focuses on source-runnable, dependency-free audits: deadline admission, fixed attempt duration, exact interval overlap, sliding-window bursts and exit-code gates. It does not reproduce Retry Lab's recovery model or UI; no code was copied.

The retry strategies are established techniques described by the [AWS Architecture Blog](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/). The contribution here is a small, inspectable analysis tool, not a claim to invent backoff or jitter. Production retry libraries execute operations; retrypace only computes schedules.

## Limitations

No success probability, outage recovery, real rate limiter, queue, adaptive feedback, Retry-After header, cancellation propagation, variable latency, transport behavior, nested retries or idempotency enforcement is modeled. Integer milliseconds quantize jitter. The reproducible PRNG is not cryptographic and is not a production retry recommendation. Limits and latency are inputs, not measurements. Never use this alone to set production limits; validate with representative load tests and service telemetry.

## Development

```sh
python -m unittest discover -s tests -v
python -m compileall -q retrypace
```

Tests cover schedules, seeded golden vectors, independent discrete-time pressure oracles, deadline boundaries, validation, CSV/JSON, CLI errors and CI gates. GitHub Actions tests Python 3.10, 3.12 and 3.13. See [contributing](CONTRIBUTING.md) and [security](SECURITY.md).

## License

[MIT](LICENSE).
