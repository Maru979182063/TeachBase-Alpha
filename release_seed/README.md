# TeachBase Release Seed input contract

This directory is the isolated implementation boundary for the current phase.
It contains input inventory, machine-readable schemas, an offline structural
validator, deterministic synthetic fixtures, an enrichment merge adapter and
test design. It does **not** contain a Java loader, Flyway migration or a real
Release Seed V1 package.

Current evidence supports these conclusions:

- 200 manual mathematics candidates were found and decoded as UTF-8.
- No completed full-batch knowledge-tagging result was found.
- No usable difficulty output was found.
- No `review_report.json` bound to a frozen payload was found.
- Release disposition is therefore approved `0`, rejected `0`, pending review
  `200`. Historical workbook statuses are not treated as Release Seed approval.

## Commands

Rebuild and validate the synthetic contract fixture:

```powershell
.\.venv-java-foundation\Scripts\python.exe release_seed\fixtures\build_fixtures.py
.\.venv-java-foundation\Scripts\python.exe release_seed\validator.py release_seed\fixtures\minimal_valid
```

Run the offline tests:

```powershell
.\.venv-java-foundation\Scripts\python.exe -m unittest discover -s release_seed\tests -v
```

Merge normalized enrichment streams without assigning approval:

```powershell
.\.venv-java-foundation\Scripts\python.exe release_seed\merge_enrichments_v1.py `
  --source source.jsonl `
  --knowledge knowledge.jsonl `
  --difficulty difficulty.jsonl `
  --output pending_review.jsonl `
  --report merge_report.json
```

The fixture is explicitly synthetic and must never be described as production
data. Java Seed Loader and the total live gate remain deferred until the shared
Review, content-hash and taxonomy foundations are complete.
