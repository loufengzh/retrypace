# Changelog

## Unreleased

- Handle JSON/CSV report output failures with exit 1 and sanitized diagnostics, including buffered flush errors and unavailable stdout. Failed output takes precedence over pressure gates.

- Reject duplicate JSON configuration keys before CLI strategy overrides or pressure gates can hide an ambiguous policy.
- Bound CLI configuration reads to 64 KiB of BOM-free UTF-8 JSON; reject nonstandard numeric constants and handle excessive nesting without a traceback.
- Add configuration-boundary regressions and document the contract in English, Chinese, Russian and German. Scheduling and seeded example results are unchanged.

## 0.1.0

- Add dependency-free Python CLI and library for reproducible all-failure retry schedules.
- Support fixed, exponential, full jitter, equal jitter and decorrelated delays.
- Admit only complete attempts within per-client deadline budgets.
- Report exact interval concurrency, sliding-window bursts, aligned buckets and retry-only peaks.
- Export JSON/CSV and provide CI pressure gates.
- Add independent pressure-oracle tests and English, Chinese, Russian and German documentation.
