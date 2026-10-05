# Model and report reference

## Scheduling

Clients have zero-based IDs. Client `i` has origin `i * stagger_ms` and absolute deadline `origin + deadline_ms`. Attempts have one-based numbers. A full attempt of `attempt_ms` must finish at or before its deadline; an attempt that would cross it is not partially executed or logged. A deadline stop means the next complete attempt could not fit, not that an admitted attempt timed out.

All admitted attempts fail. There is no success event. The next start is the prior end plus its computed delay. Stop after `max_attempts` total requests or the first unfit attempt. When the last allowed attempt fits exactly at the deadline, the stop reason is `attempt_limit`. No simulated sleeping extends the reported last admitted completion time.

## Delay rules

Let `r` be the one-based retry index after the initial attempt, `B = base_ms`, `C = cap_ms`, and `E = min(C, B * 2^(r-1))`.

| Strategy | Integer delay |
| --- | --- |
| fixed | B |
| exponential | E |
| full-jitter | draw from 0 through E inclusive |
| equal-jitter | draw from ceil(E/2) through E inclusive |
| decorrelated | min(C, draw from B through 3 * previous delay inclusive) |

For decorrelated jitter, the previous delay initially equals B. Its cap is applied **after** drawing, which can concentrate draws at C. It is not the same as drawing uniformly from B through min(C, 3 * previous). Equal jitter uses ceil(E/2) as its lower bound, so it never falls below half the ceiling in integer time.

## Reproducibility

Client `i` initializes unsigned 32-bit state as `(seed + 0x9E3779B9 * (i + 1)) mod 2^32`. Each draw updates state with `(1664525 * state + 1013904223) mod 2^32`. An inclusive integer draw `[lo, hi]` is `lo + floor(state * (hi - lo + 1) / 2^32)`. This mapping has small quantization bias when the interval size does not divide 2^32. It is adequate for reproducible illustrative schedules, not statistical inference or security.

Independent per-client streams preserve existing client schedules when the fleet grows. JSON event order is `(start_ms, client, attempt)`. The model never reads wall time or process randomness. Seeds are identical across strategy comparisons but different draw ranges and stopping points mean the compared random delays are not identical.

## Concurrency and burst metrics

Attempts occupy half-open intervals `[start_ms, end_ms)`. An attempt ending at t and another starting at t do not overlap. The implementation sums simultaneous edge deltas before computing the next interval's concurrency. A positive attempt duration is required.

- `peak_concurrency`: maximum concurrent admitted attempts.
- `time_over_concurrency_limit_ms`: total wall-clock interval length with concurrency strictly greater than the reference limit.
- `excess_concurrency_ms`: integral of `max(0, active - limit)` over time. For 40 ms with 100 active requests and limit 25, this is 3,000 request-ms.
- `peak_window_starts`: largest number of starts in **any** half-open interval `[t, t + window_ms)`. Starts exactly one window apart cannot both be counted. This avoids hiding bursts split across aligned bucket boundaries.
- `peak_aligned_bucket_starts`: largest count in a bucket `[k * window_ms, (k+1) * window_ms)`, aligned to global time zero.
- `retry_peak_concurrency` and `retry_peak_window_starts`: the corresponding metrics after excluding each client's initial request.

`buckets` is sparse: empty aligned buckets are omitted. `window_ms` is a counting interval, not a server rate limit. `concurrency_limit` never changes request admission.

## Other summary fields

- `attempts`, `retries`: admitted requests; retries exclude attempt 1.
- `clients_stopped_by_deadline`, `clients_stopped_by_attempt_limit`: exclusive and exhaustive counts of clients.
- `max_client_elapsed_ms`: maximum last admitted completion minus that client's origin; zero for clients with no admitted requests.
- `min_client_budget_remaining_ms`: `deadline_ms - max_client_elapsed_ms`; budget after the last admitted request, not after an unexecuted wait.
- `schedule_end_ms`: latest absolute admitted completion; zero for an empty schedule. Unlike client elapsed time, this includes initial staggering.

Report schema version is 1. Top-level `model` is `all-attempts-fail`. Inputs are echoed under `config`. Each event has integer `client`, `attempt`, `start_ms`, and `end_ms`. Comparisons map strategy names to complete reports without `events`.

## Complexity and limits

The CLI reads at most 64 KiB plus one detection byte from a configuration file before decoding or parsing. It requires BOM-free UTF-8 JSON with unique decoded object keys and rejects NaN/Infinity. Invalid or oversized configuration produces exit 1 and no report; overrides and gates run only after validation. This byte bound does not apply to a caller-owned dictionary passed to `Config.from_dict`, and a dictionary cannot retain evidence of duplicate JSON keys already discarded by its loader.

For N admitted attempts, scheduling is O(N), pressure analysis is O(N log N), and storage is O(N). Exponential ceilings saturate, preventing huge powers for large retry indices. Validation caps configured attempts at one million; this is a safety bound, not a latency or memory guarantee. `--summary-only` reduces serialized output, not analysis memory.

## Scope of claims

This is a deterministic scenario audit, not a queueing theorem, stress test, service availability model, exact emulation of any SDK, or guarantee of production safety. An all-failure schedule does not necessarily maximize every metric among all success/failure patterns: stopping some retries can change timing in more complex real systems. Fixed duration and noninteracting clients make this model intentionally transparent.
