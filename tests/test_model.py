import json
import random
import unittest
from dataclasses import replace
from retrypace import Config, STRATEGIES, compare, simulate
from retrypace.model import _Random, _delay, _pressure


class ScheduleTests(unittest.TestCase):
    def test_exact_exponential_schedule(self):
        config = Config(clients=1, max_attempts=5, base_ms=10, cap_ms=25,
                        attempt_ms=5, deadline_ms=1000, strategy="exponential")
        result = simulate(config)
        self.assertEqual([e["start_ms"] for e in result["events"]], [0, 15, 40, 70, 100])
        self.assertEqual(result["summary"]["max_client_elapsed_ms"], 105)
        self.assertEqual(result["summary"]["clients_stopped_by_attempt_limit"], 1)

    def test_exact_deadline_admitted(self):
        config = Config(clients=1, max_attempts=2, attempt_ms=5, base_ms=10,
                        deadline_ms=20, strategy="fixed")
        self.assertEqual(simulate(config)["summary"]["attempts"], 2)
        shorter = simulate(replace(config, deadline_ms=19))
        self.assertEqual(shorter["summary"]["attempts"], 1)
        self.assertEqual(shorter["summary"]["clients_stopped_by_deadline"], 1)
        self.assertEqual(shorter["summary"]["min_client_budget_remaining_ms"], 14)

    def test_no_attempt_fits(self):
        result = simulate(Config(clients=3, deadline_ms=0))
        self.assertEqual(result["events"], [])
        self.assertEqual(result["buckets"], [])
        self.assertEqual(result["summary"]["clients_stopped_by_deadline"], 3)
        self.assertEqual(result["summary"]["peak_concurrency"], 0)
        self.assertEqual(result["summary"]["schedule_end_ms"], 0)

    def test_relative_deadlines_and_stagger(self):
        result = simulate(Config(clients=3, max_attempts=1, attempt_ms=5,
                                 deadline_ms=5, stagger_ms=10))
        self.assertEqual([e["start_ms"] for e in result["events"]], [0, 10, 20])
        self.assertEqual(result["summary"]["max_client_elapsed_ms"], 5)
        self.assertEqual(result["summary"]["schedule_end_ms"], 25)
        self.assertEqual(result["summary"]["peak_concurrency"], 1)

    def test_seed_repeatability_and_difference(self):
        config = Config(clients=7)
        self.assertEqual(simulate(config), simulate(config))
        self.assertNotEqual(simulate(config)["events"], simulate(replace(config, seed=2))["events"])
        # Adding clients does not disturb the first clients' random streams.
        small = simulate(replace(config, clients=2))["events"]
        large = [e for e in simulate(config)["events"] if e["client"] < 2]
        self.assertEqual(small, large)

    def test_rng_golden_vector(self):
        rng = _Random(42, 0)
        self.assertEqual([rng.between(0, 1000) for _ in range(5)], [277, 721, 6, 933, 826])

    def test_strategy_bounds(self):
        for strategy in STRATEGIES:
            config = Config(base_ms=7, cap_ms=15, strategy=strategy)
            rng = _Random(0, 0)
            previous = config.base_ms
            for retry in range(1, 100):
                delay = _delay(config, retry, previous, rng)
                self.assertLessEqual(delay, config.cap_ms)
                self.assertGreaterEqual(delay, 0)
                if strategy == "fixed":
                    self.assertEqual(delay, 7)
                if strategy == "equal-jitter":
                    ceiling = min(15, 7 * 2 ** (retry - 1))
                    self.assertGreaterEqual(delay, (ceiling + 1) // 2)
                if strategy == "decorrelated":
                    self.assertGreaterEqual(delay, 7)
                previous = delay

    def test_comparison_and_event_omission(self):
        config = Config(clients=2)
        results = compare(config)
        self.assertEqual(tuple(results), STRATEGIES)
        for strategy, result in results.items():
            self.assertNotIn("events", result)
            self.assertEqual(result, simulate(replace(config, strategy=strategy), include_events=False))
        self.assertEqual(json.loads(json.dumps(results)), results)

    def test_event_invariants(self):
        for strategy in STRATEGIES:
            config = Config(clients=25, strategy=strategy, seed=0xFFFFFFFF,
                            deadline_ms=590, stagger_ms=3)
            result = simulate(config)
            summary = result["summary"]
            self.assertEqual(summary["clients_stopped_by_deadline"] +
                             summary["clients_stopped_by_attempt_limit"], config.clients)
            self.assertEqual(summary["attempts"] - summary["retries"], config.clients)
            self.assertEqual(sum(bucket["starts"] for bucket in result["buckets"]), summary["attempts"])
            for client in range(config.clients):
                events = [e for e in result["events"] if e["client"] == client]
                self.assertEqual([e["attempt"] for e in events], list(range(1, len(events) + 1)))
                for event in events:
                    self.assertLessEqual(event["end_ms"], client * 3 + 590)
                    self.assertEqual(event["end_ms"] - event["start_ms"], config.attempt_ms)
                for first, second in zip(events, events[1:]):
                    self.assertLessEqual(first["end_ms"], second["start_ms"])


class PressureTests(unittest.TestCase):
    def test_half_open_edges_and_window(self):
        events = [{"start_ms": 0, "end_ms": 10}, {"start_ms": 10, "end_ms": 20}]
        result = _pressure(events, Config(window_ms=10, concurrency_limit=1))
        self.assertEqual(result["peak_concurrency"], 1)
        self.assertEqual(result["peak_window_starts"], 1)
        self.assertEqual(result["time_over_concurrency_limit_ms"], 0)

    def test_sliding_window_catches_bucket_boundary(self):
        events = [{"start_ms": 9, "end_ms": 15}, {"start_ms": 10, "end_ms": 16}]
        result = _pressure(events, Config(window_ms=10, concurrency_limit=1))
        self.assertEqual(result["peak_window_starts"], 2)
        self.assertEqual(result["peak_aligned_bucket_starts"], 1)
        self.assertEqual(result["time_over_concurrency_limit_ms"], 5)
        self.assertEqual(result["excess_concurrency_ms"], 5)

    def test_pressure_against_discrete_oracle(self):
        rng = random.Random(13)
        for _ in range(100):
            events = []
            for _ in range(rng.randrange(1, 20)):
                start = rng.randrange(30)
                events.append({"start_ms": start, "end_ms": start + rng.randrange(1, 10)})
            window = rng.randrange(1, 10)
            limit = rng.randrange(1, 5)
            actual = _pressure(events, Config(window_ms=window, concurrency_limit=limit))
            active = [sum(e["start_ms"] <= t < e["end_ms"] for e in events) for t in range(40)]
            burst = [sum(t <= e["start_ms"] < t + window for e in events) for t in range(40)]
            self.assertEqual(actual["peak_concurrency"], max(active))
            self.assertEqual(actual["peak_window_starts"], max(burst))
            self.assertEqual(actual["time_over_concurrency_limit_ms"], sum(n > limit for n in active))
            self.assertEqual(actual["excess_concurrency_ms"], sum(max(0, n - limit) for n in active))

    def test_initial_burst_separate_from_retries(self):
        result = simulate(Config(clients=10, max_attempts=1))
        self.assertEqual(result["summary"]["peak_concurrency"], 10)
        self.assertEqual(result["summary"]["retry_peak_concurrency"], 0)
        self.assertEqual(result["summary"]["retry_peak_window_starts"], 0)


class ValidationTests(unittest.TestCase):
    def test_invalid_configs(self):
        cases = [{"clients": 0}, {"max_attempts": -1}, {"base_ms": 0},
                 {"cap_ms": 99}, {"attempt_ms": 0}, {"deadline_ms": -1},
                 {"stagger_ms": -1}, {"window_ms": 0}, {"concurrency_limit": 0},
                 {"seed": -1}, {"seed": 2**32}, {"clients": True},
                 {"attempt_ms": 1.5}, {"strategy": "unknown"}, {"clients": "5"},
                 {"clients": 1001, "max_attempts": 1000}, {"extra": 1}, [], None]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                Config.from_dict(value)

    def test_bad_library_argument(self):
        with self.assertRaises(TypeError):
            simulate({})

    def test_input_not_mutated(self):
        source = {"clients": 2}
        config = Config.from_dict(source)
        simulate(config)
        self.assertEqual(source, {"clients": 2})
        self.assertEqual(config.clients, 2)


if __name__ == "__main__":
    unittest.main()
