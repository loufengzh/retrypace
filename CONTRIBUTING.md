# Contributing

Keep the core dependency-free and deterministic. Before changing a schedule or metric, add an exact small example and state the model semantics. Include regression coverage for deadline equality and half-open interval boundaries.

Run `python -m unittest discover -s tests -v` and `python -m compileall -q retrypace` from the checkout. Changes to seeded output require explicit release notes and updates to documented example values. Keep English, Chinese, Russian and German getting-started docs consistent when CLI or configuration semantics change.

Good first improvements include additional independent property tests, resource measurements, and schema consumers. New server behavior should be an explicit model rather than silently altering the all-failure model. Discuss larger changes in an issue first. Do not include credentials, private traces, customer data or unrelated generated files.

Contributions are provided under the project's MIT license.
