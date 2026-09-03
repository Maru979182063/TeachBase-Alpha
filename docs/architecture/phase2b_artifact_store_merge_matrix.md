# Phase 2B Artifact Store Merge Matrix

The Phase 2B merge had one semantic conflict in `src/teachbase/infrastructure/artifact_store.py`. The aggregate branch keeps both parents' safety properties without changing the public JSON/text contract.

| Behavior | Aggregate branch before merge | Phase 2B head | Resolved aggregate behavior | Evidence |
| --- | --- | --- | --- | --- |
| JSON encoding | UTF-8, non-ASCII preserved, indent 2 | Same | Same | `tests/test_artifact_store.py` |
| Return contract | `None` | `None` | `None` | single-write tests |
| Temporary location | target directory | target directory | target directory | replacement-failure tests |
| Temporary name | `NamedTemporaryFile`, unique | PID/thread/UUID, unique | `NamedTemporaryFile`, unique | concurrency tests |
| Close before replace | yes | yes | yes | implementation and Windows matrix |
| Atomic replacement | `os.replace` with retry | `os.replace` with lock/retry | process lock plus 20-attempt transient retry | failure/retry tests |
| Exception cleanup | `finally` cleanup | exception cleanup | `finally` cleanup for every exception | cleanup tests |
| Concurrent same-path writes | transient retry only | serialized replacement | serialized replacement plus transient retry | multithread tests |
| Portable paths | no machine path | no machine path | no machine path | active-path policy |
| Content hash/idempotency callers | deterministic JSON bytes preserved | deterministic JSON bytes preserved | unchanged; WP-01 and renderer hash/idempotency gates remain in aggregate gate | WP-01 and renderer gates |

The store does not calculate business content hashes itself. It preserves the byte-level serialization contract consumed by the existing hash and idempotency layers.
