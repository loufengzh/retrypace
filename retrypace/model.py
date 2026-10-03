"""Integer-millisecond, all-failure schedule model (schema version 1)."""
from dataclasses import asdict, dataclass, fields, replace
from collections import Counter

STRATEGIES = ("fixed", "exponential", "full-jitter", "equal-jitter", "decorrelated")
MAX_EVENTS = 1_000_000


@dataclass(frozen=True)
class Config:
    clients: int = 100
    max_attempts: int = 5
    base_ms: int = 100
    cap_ms: int = 2000
    attempt_ms: int = 50
    deadline_ms: int = 3000
    stagger_ms: int = 0
    window_ms: int = 100
    concurrency_limit: int = 20
    seed: int = 1
    strategy: str = "full-jitter"

    def __post_init__(self):
        for field in fields(self):
            if field.name == "strategy":
                continue
            value = getattr(self, field.name)
            if type(value) is not int:
                raise ValueError(f"{field.name} must be an integer")
            minimum = 0 if field.name in ("deadline_ms", "stagger_ms", "seed") else 1
            maximum = 0xFFFFFFFF if field.name == "seed" else 1_000_000_000
            if not minimum <= value <= maximum:
                raise ValueError(f"{field.name} must be in [{minimum}, {maximum}]")
        if self.strategy not in STRATEGIES:
            raise ValueError(f"strategy must be one of {', '.join(STRATEGIES)}")
        if self.cap_ms < self.base_ms:
            raise ValueError("cap_ms must be >= base_ms")
        if self.clients * self.max_attempts > MAX_EVENTS:
            raise ValueError(f"clients * max_attempts must be <= {MAX_EVENTS}")

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("configuration must be a JSON object")
        unknown = set(value) - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError(f"unknown configuration keys: {', '.join(sorted(unknown))}")
        return cls(**value)


class _Random:
    """Documented 32-bit LCG; reproducible independently of Python random."""
    def __init__(self, seed, client):
        self.state = (seed + 0x9E3779B9 * (client + 1)) & 0xFFFFFFFF

    def between(self, low, high):
        self.state = (1664525 * self.state + 1013904223) & 0xFFFFFFFF
        return low + (self.state * (high - low + 1) // 2**32)


def _delay(config, retry, previous, rng):
    # Saturating multiplication avoids enormous integers for long schedules.
    ceiling = config.base_ms
    for _ in range(retry - 1):
        if ceiling >= config.cap_ms:
            break
        ceiling = min(config.cap_ms, ceiling * 2)
    if config.strategy == "fixed":
        return config.base_ms
    if config.strategy == "exponential":
        return ceiling
    if config.strategy == "full-jitter":
        return rng.between(0, ceiling)
    if config.strategy == "equal-jitter":
        return rng.between((ceiling + 1) // 2, ceiling)
    return min(config.cap_ms, rng.between(config.base_ms, previous * 3))


def _pressure(events, config):
    starts = sorted(event["start_ms"] for event in events)
    edges = Counter()
    buckets = Counter()
    for event in events:
        edges[event["start_ms"]] += 1
        edges[event["end_ms"]] -= 1
        buckets[event["start_ms"] // config.window_ms] += 1
    active = peak = over_ms = excess_ms = 0
    previous = 0
    for time, delta in sorted(edges.items()):
        span = time - previous
        if active > config.concurrency_limit:
            over_ms += span
            excess_ms += span * (active - config.concurrency_limit)
        active += delta
        peak = max(peak, active)
        previous = time
    left = sliding_peak = 0
    for right, time in enumerate(starts):
        while starts[left] <= time - config.window_ms:
            left += 1
        sliding_peak = max(sliding_peak, right - left + 1)
    return {
        "peak_concurrency": peak,
        "time_over_concurrency_limit_ms": over_ms,
        "excess_concurrency_ms": excess_ms,
        "peak_window_starts": sliding_peak,
        "peak_aligned_bucket_starts": max(buckets.values(), default=0),
        "buckets": [{"start_ms": index * config.window_ms, "starts": count}
                    for index, count in sorted(buckets.items())],
    }


def simulate(config=None, *, include_events=True):
    """Return JSON-compatible report. Every admitted attempt is assumed to fail.

    A full attempt must fit the client's relative deadline. Attempts occupy
    [start_ms, end_ms); waiting starts after completion, never after start.
    """
    if config is None:
        config = Config()
    if not isinstance(config, Config):
        raise TypeError("config must be a Config")
    events = []
    stopped = Counter()
    elapsed = []
    for client in range(config.clients):
        origin = client * config.stagger_ms
        time = origin
        previous = config.base_ms
        rng = _Random(config.seed, client)
        last_end = origin
        for attempt in range(1, config.max_attempts + 1):
            if time + config.attempt_ms > origin + config.deadline_ms:
                stopped["deadline"] += 1
                break
            last_end = time + config.attempt_ms
            events.append({"client": client, "attempt": attempt,
                           "start_ms": time, "end_ms": last_end})
            if attempt == config.max_attempts:
                stopped["attempt_limit"] += 1
                break
            previous = _delay(config, attempt, previous, rng)
            time = last_end + previous
        elapsed.append(last_end - origin)
    events.sort(key=lambda event: (event["start_ms"], event["client"], event["attempt"]))
    pressure = _pressure(events, config)
    retries = [event for event in events if event["attempt"] > 1]
    retry_pressure = _pressure(retries, config)
    report = {
        "schema_version": 1,
        "model": "all-attempts-fail",
        "config": asdict(config),
        "summary": {
            "attempts": len(events), "retries": len(retries),
            "clients_stopped_by_deadline": stopped["deadline"],
            "clients_stopped_by_attempt_limit": stopped["attempt_limit"],
            "max_client_elapsed_ms": max(elapsed, default=0),
            "min_client_budget_remaining_ms": config.deadline_ms - max(elapsed, default=0),
            "schedule_end_ms": max((event["end_ms"] for event in events), default=0),
            **{key: value for key, value in pressure.items() if key != "buckets"},
            "retry_peak_concurrency": retry_pressure["peak_concurrency"],
            "retry_peak_window_starts": retry_pressure["peak_window_starts"],
        },
        "buckets": pressure["buckets"],
    }
    if include_events:
        report["events"] = events
    return report


def compare(config=None):
    """Compare every strategy using identical configuration and seed."""
    config = Config() if config is None else config
    return {strategy: simulate(replace(config, strategy=strategy), include_events=False)
            for strategy in STRATEGIES}
