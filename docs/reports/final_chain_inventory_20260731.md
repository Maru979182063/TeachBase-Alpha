# Final Chain Inventory 20260731

Baseline: `integration/repository-scope-clean-20260715`

Baseline SHA: `b96a400daadd11fd496ecc47152861f3d5496dae`

Inventory branch: `audit/final-chain-inventory-20260731`

This inventory separates product-facing final chains from lower-level technical
pipeline entries. The current `config/pipeline_registry.yaml` has four technical
pipelines, but the intended final product surface is a 2x2 matrix.

Confirmation status: these four final chains are the product-owner taxonomy
stated in conversation and cross-checked against prior Codex task summaries.
The repository does not yet encode this taxonomy as a canonical registry, so
current code is supporting evidence rather than the source of truth.

Historical note: an older handoff used three pipelines: DOCX, PDF math, and
English image-PDF. That was a useful state at the time, but later work split
DOCX into math and English final-facing chains. The current intended surface is
therefore four chains, while reading / grammar / writing / cloze remain family
branches inside the PDF English chain.

| Final chain | Input | Subject | Current status |
| --- | --- | --- | --- |
| `doc_math` | DOCX | math | Partial isolated implementation and tests, not registered as a final chain |
| `doc_english` | DOCX | english | Conversation-confirmed chain; old local has experimental protected segment, cleanroom baseline does not |
| `pdf_math` | PDF | math | Covered by generic `split_v03` validation path, not separated as `pdf_math` |
| `pdf_english` | PDF | english | `english_text_first_v05` is registered experimental/isolated; `split_v03` also has legacy English support |

## Conversation Evidence

Prior task summaries support the taxonomy, but they are evidence, not executable
instructions:

- `three-pipeline handoff` recorded the older three-pipeline handoff: DOCX,
  PDF math, English image-PDF.
- `DOCX native-first audit` established the DOCX-native-first principle:
  preserve Word XML, `word/media`, OMML/formula structure, and only use page
  rendering as fallback evidence.
- `English DOCX chain discussion` established DOCX English as a distinct chain
  and later added a protected downstream runner around repair gate, field
  normalization, and parent/child projection.
- `English image-PDF audit` established PDF English as image-PDF text-first /
  graph-first, with reading, grammar, writing, and cloze as subfamilies.

## Last Artifact Time Audit

This audit also inspected the old full local project on 2026-07-31 and refreshed
DOCX English evidence on 2026-08-03. Paths below
are relative to that observed project root and are not reproducible input
contracts.

| Chain | Strongest retained local artifact time | Evidence | Interpretation |
| --- | --- | --- | --- |
| `doc_english` | `2026-08-03 18:03:35` | `outputs/delivery_packs/english_docx_doc4_seven_choice_parentraw_translation_review_20260803_v03.zip` plus reading full-scope translation v02 | Latest protected child-enrichment/business-review surface. It upgrades reading to v0.6 full-scope translation and seven-choice to v0.6 parent-raw translation. The canonical raw-DOCX entrypoint remains unchanged. |
| `doc_math` | `2026-07-28 14:34:52` | `config/docx_math_pipeline_final_active_manifest.json` | Strong manifest/code/thread evidence, but observed local active output roots are empty after cleanup. Do not infer current artifact completeness from the directory timestamps alone. |
| `pdf_english` | `2026-07-24 18:12:27` | `outputs/en_full3docs_v20_pkg_20260724.zip` | Strongest retained local package evidence: 136 records, 82 page assets, Runtime import and database writes disabled. Later 2026-07-28 graph-first/cloze work is supported by thread/docs, but observed local graph-first dirs are incomplete or empty. |
| `pdf_math` | `2026-07-21 16:51:40` | `outputs/review_packages/s_math47_overlap24_final2_colleague_review_20260721_165138.zip` | Strongest retained review-package evidence: 47 questions, 45 pass, 2 needs_review, 0 fails. The 47-question run allowed MinerU fallback, but prepared records show `mineru_fallback=null` and no `_mineru_fallback` output files; MinerU is fallback capability, not the primary detector path. |

Observed empty or incomplete local roots include:

- `outputs/docx_math_pipeline_final_v0_1`
- `outputs/docx_math_fullchain_orchestrator_v0_1`
- `outputs/docx_math_delivery_packages_20260728`
- `outputs/english_text_first_graph_first`
- `outputs/english_text_first_pipeline_v02_spec_20260715`
- `outputs/en_downstream_fixed_packages_20260728`

Selection rule: a directory whose name says `final`, `full`, `graph_first`,
`probe`, or `candidate` is not enough. Promote only when manifest, summary, and
actual retained artifact files agree.

## Protection Candidates

This is the pre-registry protection list for cleanup. It is deliberately more
conservative than a final registry: when evidence is incomplete, protect the
code from deletion but do not promote it as a completed production chain.

| Chain | Protection confidence | Protect as | Do not overclaim |
| --- | --- | --- | --- |
| `doc_math` | High | User-named final DOCX math pipeline with clean-branch handoff, unique entrypoint, active config, and 47-file inventory | Do not use the dirty old local worktree as the clean baseline; prefer the clean branch/commit or the handoff inventory |
| `doc_english` | High | Same-day stage0 isolated environment plus protected doc5/doc6 downstream runner | Latest protected evidence covers doc5/doc6 only and starts from existing artifacts, not raw DOCX entry |
| `pdf_english` | Medium-high | Final-chain identity and entry contract for `english_text_first_graph_first`, plus retained v20 package and user-confirmed 2026-07-28 v02/graph-first/cloze lineage | 2026-07-28 graph-first smoke artifacts and active manifest are missing in the moved local copy; cloze is pages 1-8 candidate only |
| `pdf_math` | High | Retained 47-question final2 package and long asset/refine/audit suite | MinerU is a gated fallback capability, not the primary detector path in the 47-question run |

### `doc_math` protection candidate

Handoff package evidence observed on 2026-07-31:

- Package label: `docx_math_final_pipeline_handoff_20260731`
- Files: `HANDOFF.md`, `final_chain_file_inventory.json`
- Inventory: `47` files, `missing=0`
- Declared clean branch:
  `origin/codex/docx-math-final-pipeline-clean-v01`
- Declared clean commit:
  `fabc70f Add isolated DOCX math final pipeline`
- Dirty local warning: current old local worktree is mixed with English-line and
  staged files; do not use it as a clean implementation baseline.

Canonical definition evidence in the old local project:

- `config/docx_math_pipeline_final_active_manifest.json`
- `config/docx_math_pipeline_final_v01.yaml`

Manifest claims:

- Active pipeline id: `docx_math_pipeline_final_v01`
- Active name: `DOCX Math Native Final Pipeline`
- Status: `experimental_final_candidate`
- Entrypoint: `tools/docx_math_pipeline_final_orchestrator_v01.py`
- Owned output root: `outputs/docx_math_pipeline_final_v0_1`
- Runtime import: disabled
- Database writes: disabled
- Last updated: `2026-07-27`

Protected node candidates:

- `tools/docx_native_stage0_router_v01.py`
- `tools/docx_native_block_tagger_v01.py`
- `tools/docx_asset_role_visual_tagger_v01.py`
- `tools/docx_question_boundary_cutter_v01.py`
- `tools/docx_math_pipeline_final_orchestrator_v01.py`
- `tools/docx_question_complexity_router_v01.py`
- `tools/docx_question_part_normalizer_v01.py`
- `tools/docx_question_part_long_normalizer_v01.py`
- `tools/docx_question_part_twostage_probe_v01.py`
- `tools/docx_math_source_backed_draft_builder_v01.py`
- `tools/docx_math_fullchain_orchestrator_v01.py`
- `tools/docx_math_build_side_by_side_review_v01.py`
- `tools/docx_native_formula_token_stream_v01.py`
- `tools/docx_run_math_normalizer_v01.py`
- `tools/docx_math_question_refiner_v01.py`
- `tools/docx_math_long_composite_refiner_v01.py`
- `tools/docx_math_long_packet_assembler_v01.py`
- `tools/docx_math_refine_gate_repair_orchestrator_v01.py`
- `tools/docx_native_transcription_package_builder_v01.py`

Explicitly do not promote as final:

- `tools/docx_math_pipeline_orchestrator_v01.py`
- `tools/docx_question_grouper_v01.py`
- `outputs/docx_question_grouper_v0_1`
- `outputs/docx_math_pipeline_orchestrator_v0_1`
- `outputs/docx_native_pipeline_v0_1`
- `outputs/docx_native_model_segment_v0_1`
- `outputs/docx_native_text_repair_model_v0_1`
- `outputs/docx_native_boundary_resolver_v0_1`

Product-owner correction on 2026-07-31: DOCX math had already been stable and
was explicitly named as the final chain. The handoff confirms the unique
entrypoint, active configs, clean branch/commit, and a complete 47-file critical
inventory. Interpretation: protect this as a high-confidence named final DOCX
math implementation. The old local worktree is a storage attic, not the clean
foundation; implementation work should start from the clean branch/commit when
possible, or from the handoff inventory when network access is unavailable.

### `doc_english` protection candidate

Canonical definition evidence in the old local project:

- `config/english_docx_native_md/active_manifest.json`
- `config/english_docx_native_md/group_repair_gate_v01.json`

Manifest claims:

- Pipeline id: `english_docx_native_md_v01`
- Name: `English DOCX Native Markdown Isolated Environment`
- Status: `stage0_isolated_candidate`
- Entrypoint: `tools/english_docx_native_md_v01.py`
- Owned output root: `outputs/english_docx_native_md_v0_1`
- Runtime import: disabled
- Database writes: disabled
- Last updated: `2026-07-31`

Protected node candidates:

- `tools/english_docx_native_md_v01.py`
- `tools/english_docx_group_boundary_cutter_v01.py`
- `tools/english_docx_group_itemizer_v01.py`
- `tools/english_docx_child_skill_tagger_v01.py`
- `tools/english_docx_group_repair_gate_v01.py`
- `tools/english_docx_group_field_normalizer_v01.py`
- `tools/english_docx_parent_child_projection_v02.py`
- `tools/english_docx_reading_child_enhancer_v01.py`
- `tools/english_docx_cloze_child_skill_tagger_v01.py`
- `tools/english_docx_grammar_child_formatter_v01.py`
- `tools/english_docx_seven_choice_child_formatter_v01.py`
- `tools/english_docx_parent_only_review_pack_v01.py`
- `tools/english_docx_optimized_review_renderer_v01.py`
- `tools/english_docx_integrated_chain_runner_v01.py`

Latest protected run evidence:

- Run root:
  `outputs/english_docx_integrated_chain_v0_1/protected_doc5_doc6_20260731_v01`
- Covered docs: `doc5_continuation_writing`, `doc6_practical_writing`
- Runner status: `ok` for both docs
- Fallback events: `0`
- Projection warnings: `0`
- Repair selected mode: `repaired` for both docs

Additional delivery package evidence:

- `outputs/delivery_packs/english_docx_docs1_6_final_20260731_v01.zip`
- Timestamp: `2026-07-31 10:12:29`
- Scope: docs1-6 delivery packaging evidence, but it predates the later
  protected doc5/doc6 run.

Late DOCX English update accepted on 2026-07-31:

- Protected delivery:
  `outputs/delivery_packs/english_docx_doc3_tagged_final_20260731_v04.zip`
- Timestamp: `2026-07-31 15:00:42`
- Doc: `doc3_cloze_20_answers`
- Source projection:
  `outputs/english_docx_parent_child_projection_v0_2/doc3_cloze_20_answers_20260731_v04/parent_child_projection.json`
- Summary: 20 groups, 300 children, 0 missing options, 0 missing tags,
  300 HTML option headings, no mojibake marker, zip `testzip=None`.
- `english_docx_doc3_tagged_final_20260731_v03` was not promoted because v04
  supersedes it and carries stronger HTML/encoding checks.

Later DOCX English update accepted on 2026-07-31:

- Latest protected doc3 delivery:
  `outputs/delivery_packs/english_docx_doc3_tagged_final_20260731_v10.zip`
- Timestamp: `2026-07-31 15:23:58`
- Source projection:
  `outputs/english_docx_parent_child_projection_v0_2/doc3_cloze_20_answers_20260731_v10/parent_child_projection.json`
- Summary: 20 groups, 300 children, 300 model-relevant contexts, 0 missing
  options, 0 missing tags, 0 previous-numbered-blank violations, 300 child
  option headings, 0 literal blank tokens, no mojibake marker, zip
  `testzip=None`.
- v04 remains protected predecessor evidence; v08/v09/v10 are later iterations,
  and v10 is the promoted doc3 delivery evidence because it carries the latest
  projection source and the strongest blank/render checks.

Same batch protected review/delivery surfaces:

- Parent-only review packs:
  `english_docx_doc1_parent_only_20260731_v01`,
  `english_docx_doc2_parent_only_20260731_v01`,
  `english_docx_doc4_parent_only_20260731_v01`.
- Unknown-quarantine fixes:
  `english_docx_doc5_unknownfix_20260731_v01`,
  `english_docx_doc6_unknownfix_20260731_v01`.
- Optimized review packs:
  `english_docx_doc1_optimized_review_20260731_v01` through
  `english_docx_doc6_optimized_review_20260731_v01`.
- These are registered as protected review/packaging surfaces, not as a new
  canonical entrypoint. The canonical DOCX English entry remains
  `tools/english_docx_native_md_v01.py`, with the protected segment runner at
  `tools/english_docx_integrated_chain_runner_v01.py`.

DOCX English four-type child-enrichment update accepted on 2026-08-03:

- Latest protected business review package:
  `outputs/delivery_packs/english_docx_four_type_business_review_20260803_v07.zip`
- Timestamp: `2026-08-03 13:44:27`
- Zip integrity: `testzip=None`, 5 entries, SHA-256
  `1628b177c4529977653befce08baa742d25b9ee905a0c72f8bfb553d2f33ad12`.
- Covered types: cloze, grammar, reading, seven-choice.
- Cloze source remains `english_docx_doc3_tagged_final_20260731_v10`: 20
  groups, 300 children.
- Grammar source:
  `outputs/english_docx_grammar_child_formatter_v0_1/doc1_grammar_full_20260803_v06`,
  doc `doc1_zhuanlian1`, 17 groups, 156 children, `status_counts.ok=17`,
  `issue_count=0`.
- Reading source:
  `outputs/english_docx_reading_child_enhancer_v0_1/doc2_full_reading_child_enhanced_20260803_v01`,
  doc `doc2_zhuanlian2`, 19 groups, 58 children, `status_counts.ok=19`,
  `issue_count=0`.
- Seven-choice source:
  `outputs/english_docx_seven_choice_child_formatter_v0_1/doc4_seven_full_fillprev_20260803_v01`,
  doc `doc4_seven_choice`, 13 groups, 61 children, `status_counts.ok=13`,
  `issue_count=0`. Its delivery zip also has `testzip=None`.
- Registered as protected post-projection child-enrichment and business review
  evidence. It does not replace the canonical raw DOCX entrypoint.

Later DOCX English reading/seven-choice update accepted on 2026-08-03:

- Reading full-scope translation business review:
  `outputs/delivery_packs/english_docx_reading_full_scope_translation_business_review_20260803_v02.zip`
- Reading summary: doc `doc2_reading`, 19 groups, 58 children,
  `status_counts.ok=19`, `issue_count=0`, prompt version
  `english_docx_reading_child_enhancer_v0.6_20260803`, zip `testzip=None`,
  SHA-256 `84ec070a7f02b93f21aea5854bf3b46c96d65df3598681d2fedf2a9c0f44ae6d`.
- Seven-choice parent-raw translation review:
  `outputs/delivery_packs/english_docx_doc4_seven_choice_parentraw_translation_review_20260803_v03.zip`
- Seven-choice summary: doc `doc4_seven_choice`, 13 groups, 61 children,
  `status_counts.ok=13`, `issue_count=0`, prompt version
  `english_docx_seven_choice_child_formatter_v0.6_parent_raw_translation_20260803`,
  `fallback_rounds_configured=1`, zip `testzip=None`, SHA-256
  `0cc2fae7edb8ec504afdbb0bf6a1df8b237696ddc9b590b73a636d0fb40b248c`.
- Earlier same-afternoon seven-choice sample, paragraph-context, and
  `needs_review` runs remain iteration evidence. The promoted late seven-choice
  evidence is v03 because it is full-doc, reconciled, packaged, and has zero
  issues.

Product-owner correction on 2026-07-31: DOCX English was run on the morning of
2026-07-31 and is comparatively easy to confirm. Interpretation: this protected
segment is not a guess; the same-day local run evidence is strong. Still avoid
calling it a complete raw-DOCX-entry production chain unless the upstream
raw-entry run artifacts are added to the registry evidence.

### `pdf_english` protection candidate

Confidence breakdown:

- Final-chain identity and entry contract: High.
- Retained artifact completeness in the moved local copy: Medium.

Handoff package evidence observed on 2026-07-31:

- Package label: `english_text_first_graph_first_handoff`
- Zip integrity: pass
- Files:
  `README_HANDOFF.md`, `PIPELINE_CONTRACT.md`, `RUNBOOK.md`,
  `HANDOFF_CHECKLIST.md`
- Declared pipeline name: `english_text_first_graph_first`
- Declared unique entry:
  `config/english_text_first_graph_first/active_manifest.json`
- Declared manifest gate:
  `python tools/english_text_first_graph_first_manifest_check.py`
- Declared success marker:
  `english_text_first_graph_first_manifest_valid`

Declared final-chain node order:

1. `node1_vlm_transcriber`
2. `node1b_block_attribute_tagger`
3. `node2_sliding_window_composer`
4. `node2d_document_group_deduper`
5. `node3_group_normalizer`
6. `node3b_group_relation_resolver`
7. `node3c_group_ownership_reconciler`
8. `node4_source_backed_draft_builder`
9. `node5_packet_builder`
10. `node5a_continuation_repair`
11. `node5b_refiner`
12. `node6a_projection_planner`
13. `node6b_render_normalizer`

Declared prior smoke artifacts from the original EDY machine:

- `outputs/english_text_first_graph_first/final_chain_smoke_20260728.zip`
- `outputs/english_text_first_graph_first/final_chain_smoke_20260728/`

Declared prior smoke scope:

- Node1 / Node1b: reading, grammar, writing, and cloze each 1 page;
  all `parsed=1`, `valid=1`.
- Node2 -> Node6b: reading `p001-p002`, grammar `p001`, writing `p001`,
  cloze `p001`.
- Runtime import: disabled.
- Database write: disabled.

Forbidden selection rules from the handoff:

- Do not guess the final chain by latest directory timestamp.
- Do not promote `backup`, `probe`, `smoke`, `plain_full`, or `badcase`
  directories as the final chain.
- Do not treat `QuestionPacket` as source truth.
- Projection and render nodes must not mutate source or `source_refs`.
- Do not use one mixed `READY/HOLD` gate to hide semantic, evidence, and
  projection state differences.

Strongest retained package:

- `outputs/en_full3docs_v20_pkg_20260724.zip`
- Timestamp: `2026-07-24 18:12:27`
- Records: `136`
- Page assets: `82`
- Reading records: `40`
- Grammar records: `58`
- Writing records: `38`
- Runtime import: disabled
- Database writes: disabled

Cleanroom isolated gate evidence:

- `config/english_text_first_v05.yaml`
- `tools/english_text_first_v05_pipeline.py`
- `tools/english_text_first_sidecar_graph_v01.py`
- `tools/english_text_first_v05_model_gate.py`
- `tests/test_english_text_first_v05_pipeline.py`
- `tests/test_english_text_first_sidecar_graph_v01.py`

Old-local long-lineage evidence:

- `docs/english_text_first_graph_first_environment.md`
- `config/english_text_first_v02.yaml`
- `tools/english_text_first_graph_first_manifest_check.py`

Protected old-local long-lineage node candidates:

- `tools/english_text_first_controlled_node1_vlm_transcriber.py`
- `tools/english_text_first_controlled_node1b_attribute_tagger.py`
- `tools/english_text_first_sliding_window_composer_v01.py`
- `tools/english_text_first_group_normalizer_v01.py`
- `tools/english_text_first_group_relation_resolver_v01.py`
- `tools/english_text_first_group_ownership_reconciler_v01.py`
- `tools/english_text_first_source_backed_draft_builder_v01.py`
- `tools/english_text_first_node4b_field_role_resolver_v01.py`
- `tools/english_text_first_question_packet_builder_v01.py`
- `tools/english_text_first_question_packet_refiner_v01.py`
- `tools/english_text_first_runtime_projection_planner_v01.py`
- `tools/english_text_first_question_render_normalizer_v01.py`
- `tools/english_text_first_render_verifier_repair_v01.py`
- `tools/english_text_first_render_gate_point_repair_v01.py`
- `tools/english_text_first_question_candidate_auditor_v01.py`
- `tools/english_text_first_graph_first_manifest_check.py`

Graph-first 2026-07-28 status:

- The environment doc names
  `config/english_text_first_graph_first/active_manifest.json`, but that
  manifest is missing or not retained in the observed old local project.
- Observed `outputs/english_text_first_graph_first` and downstream fixed package
  roots are empty or incomplete.
- The handoff-declared `final_chain_smoke_20260728.zip` and
  `final_chain_smoke_20260728/` are also missing in the currently readable old
  local copy.
- Product-owner correction on 2026-07-31: the last PDF English result batch was
  indeed produced on 2026-07-28.
- Same-day code/config/prompt evidence exists:
  `tools/english_text_first_full_chain_runner_v01.py`,
  `tools/english_text_first_question_packet_refiner_v01.py`,
  `tools/english_text_first_question_render_normalizer_v01.py`,
  `tools/english_text_first_review_pack_renderer_v01.py`,
  `config/english_text_first_v02.yaml`,
  `docs/english_text_first_graph_first_environment.md`, and cloze prompt files.
- Cloze is pinned as pages 1-8 review-candidate only, not full-PDF production
  confirmation.
- Node6d exists in `config/english_text_first_v02.yaml`, but the graph-first
  environment doc says it is not the pinned active final gate.

Interpretation: the handoff confirms the final-chain identity and entry
contract. Protect `english_text_first_graph_first` as the PDF English final-chain
definition, but do not let the missing manifest and missing smoke artifacts
masquerade as artifact-complete proof in this moved local copy. This one is like
a long bridge where the route map and engineering rules are now recovered, while
the latest inspection plaque still needs to be restored or regenerated.

## Registry Readiness Smoke

Smoke run date: `2026-07-31`.

New protected final-chain registry:

- `config/final_chain_registry.yaml`
- `tests/test_final_chain_registry.py`
- `tools/validate_final_chain_registry.py`
- `tools/classify_final_chain_surface.py`
- `tests/test_final_chain_surface_classifier.py`
- `npm run test:final-chain-registry`

Smoke results:

| Chain | Result | Registry readiness |
| --- | --- | --- |
| `doc_math` | Pass | `ready` |
| `doc_english` | Pass | `ready_for_protected_segment` |
| `pdf_math` | Pass | `ready` |
| `pdf_english` | Partial | `protected_definition_ready_needs_artifact_restore_or_smoke_rerun` |

DOCX math smoke:

- Handoff inventory: `47` files, `missing=0`.
- Observed old-local hash check: `observed_missing_count=0`,
  `sha256_mismatch_count=0`.
- `tools/docx_math_pipeline_final_orchestrator_v01.py --help` loads.
- Active manifest parses with `active_pipeline_id=docx_math_pipeline_final_v01`.
- Runtime import and database write are disabled.

DOCX English smoke:

- `config/english_docx_native_md/active_manifest.json` parses.
- `tools/english_docx_integrated_chain_runner_v01.py --help` loads.
- doc5/doc6 protected run summaries are `status=ok`.
- `fallback_events_count=0`.
- Field normalizer summaries are `status=ok`, `issue_count=0`.
- Projection summaries have `warning_count=0`.
- Runtime import and database write are disabled.

PDF math smoke:

- `tools/audit_question_asset_package.py --help` loads.
- Retained final2 zip `testzip=None`.
- Retained final2 zip contains the asset audit summary.
- Audit rerun on the final2 `reconciled_refined_manifest.json` returns:
  47 questions, 45 pass, 2 needs_review, 0 fail.
- Audit rerun output label:
  `pdf_math_final2_smoke_20260731_142421`.

PDF English smoke:

- Handoff zip `testzip=None`.
- Handoff declares unique entry:
  `config/english_text_first_graph_first/active_manifest.json`.
- Handoff declares manifest gate:
  `python tools/english_text_first_graph_first_manifest_check.py`.
- `tools/english_text_first_graph_first_manifest_check.py --help` loads in the
  old local copy.
- 2026-07-28 `config/english_text_first_v02.yaml`,
  `docs/english_text_first_graph_first_environment.md`, and
  `tools/english_text_first_full_chain_runner_v01.py` exist.
- Cleanroom `english_text_first_v05` portable regression passes: 7 tests.
- Blocking restore items in the moved local copy:
  `config/english_text_first_graph_first/active_manifest.json`,
  `outputs/english_text_first_graph_first/final_chain_smoke_20260728.zip`,
  and `outputs/english_text_first_graph_first/final_chain_smoke_20260728/`.

Cleanroom regression checks:

- `tools/validate_final_chain_registry.py --json`: `ok=true`,
  `chain_count=4`, `error_count=0`, `warning_count=7`.
- Final-chain registry warnings are expected at this stage: they mark
  doc/math, doc/english, and PDF English graph-first files that are protected by
  handoff or old-local evidence but not yet imported into the cleanroom copy.
- `tests/test_final_chain_registry.py`: 7 passed.
- `npm.cmd run test:final-chain-registry` with the cleanroom `.venv` on PATH:
  passed.
- Final-chain surface classifier tests: passed.
- `tests/test_english_text_first_v05_pipeline.py` +
  `tests/test_english_text_first_sidecar_graph_v01.py`: 7 passed.
- DOCX native repair tests: 10 passed.
- Architecture boundary tests: 7 passed.

Non-destructive surface classification reports:

- `docs/reports/final_chain_surface_classification_old_local_20260731.json`
- `docs/reports/final_chain_surface_classification_old_local_20260731.md`
- `docs/reports/final_chain_surface_classification_cleanroom_20260731.json`
- `docs/reports/final_chain_surface_classification_cleanroom_20260731.md`

Non-destructive cleanup candidate reports:

- `docs/reports/cleanup_candidates_old_local_20260731.json`
- `docs/reports/cleanup_candidates_old_local_20260731.md`
- `docs/reports/cleanup_candidates_cleanroom_20260731.json`
- `docs/reports/cleanup_candidates_cleanroom_20260731.md`

Old local classification summary:

- Protected final-chain surface: 153.
- Known non-final legacy: 2.
- Historical/probe surface: 421.
- Chain-adjacent needs review: 338.
- Final-like names needing review: 38.
- Unregistered output surface: 609.

Cleanroom classification summary:

- Protected final-chain surface: 32.
- Historical/probe surface: 20.
- Chain-adjacent needs review: 12.
- Final-like names needing review: 20.
- Unregistered output surface: 3.

Cleanup candidate summary:

| Target | Archive candidates | Must review | Notes |
| --- | ---: | ---: | --- |
| old full local project | 548 | 522 | 2 parent dirs contain protected surfaces; 320 candidates are referenced; 175 are historical-looking code/test surfaces |
| cleanroom partial project | 5 | 38 | Code/test entries are review-only, not deletion candidates |

Deletion rule after this report: only future items that are unreferenced,
outside protected paths, outside code/test/config surfaces, and already archived
with a rollback path may become delete candidates. Nothing in these reports is
deleted automatically.

## Chain Notes

### `doc_math`

Evidence:

- `tools/docx_native_formula_token_stream_v01.py`
- `tools/docx_native_formula_providers.py`
- `tools/docx_native_text_repair_model_node_v01.py`
- `tests/test_docx_native_formula_providers.py`
- `tests/test_docx_native_formula_token_stream_v01.py`
- `tests/test_docx_native_text_repair_model_node_v01.py`

Current shape:

- Has formula/token extraction, image placeholder preservation, and recorded/mock
  text repair test coverage in the cleanroom branch.
- The old full local project has a `docx_math_pipeline_final_active_manifest.json`
  that marks `tools/docx_math_pipeline_final_orchestrator_v01.py` as an
  experimental final candidate, with Runtime import and database writes disabled.
- The old full local active output roots observed during this audit are empty;
  prior thread evidence says confusing DOCX math outputs were intentionally
  removed after the final chain was pushed to a clean branch.
- Tests assert no Runtime import and no database write for packet generation.
- Live model repair is possible only when explicitly given ARK credentials.
- Not registered as a final chain in the cleanroom `pipeline_registry.yaml`.

### `doc_english`

Evidence:

- `tests/fixtures/english/minimal_bundle.json`
- `tests/fixtures/three_track/english_senior_bundle.json`
- `tests/api/runtime_api_e2e.mjs`
- `tools/run_staging_validation.mjs`

Current shape:

- The cleanroom branch mostly has downstream English Runtime/export evidence,
  not the old local DOCX English implementation.
- The old full local project has a tracked-looking but unmerged DOCX English
  chain under `tools/english_docx_*` and `config/english_docx_native_md`.
- The latest retained local DOCX English protected run is doc5/doc6 only:
  repair gate -> field normalizer -> parent/child projection, both `status=ok`.
- This is not yet a clean package-level final chain or registry entry.

### `pdf_math`

Evidence:

- `config/pipeline_registry.yaml` entry `split_v03`
- `tools/run_split_v03_full_doc.py`
- `tools/split_pipeline_v03.py`
- `tests/test_split_v03_contract.py`
- `tests/test_split_v03_coordinate_integrity.py`
- `tests/test_split_v03_golden_cases.py`

Current shape:

- The cleanroom baseline only exposes the generic `split_v03` validation path,
  but the old full local project contains a larger PDF math production-style
  line around `tools/run_question_ingest_skill.py`.
- The strongest retained large-suite evidence is the 2026-07-21 47-question
  overlap24 run and final2 colleague review package.
- That larger suite should be treated as a multi-node assembly line:
  source split -> planner/image-need gate -> candidate split -> visual
  transcription/recovery -> format-normalize backfill -> figure detection ->
  assetize -> consolidate -> reconcile/refine -> audit/package.
- The 47-question run reports planner `ok_count=47`,
  `needs_figure_detection_count=5`, `no_figure_count=42`, and
  `total_tokens=101863`.
- Transcription reports `ok_count=46`, one final failed question `tq_002`.
- Format-normalize backfill is present in the runner, but this main run reports
  `skipped_already_normalized`; the separate formula patch regression provides
  evidence for the Markdown/LaTeX library gate and split-macro repair path.
- Asset bundle reports 47 questions and 52 assets.
- Reconcile/refine reports 5 `refined_by_model` quality actions, plus visual
  insert anchor review actions for the 5 image-bearing questions.
- Final audit reports 45 pass, 2 needs_review (`tq_017`, `tq_028`), and 0 fail.
- MinerU fallback exists as an explicit gated fallback in
  `tools/prepare_option_visual_source.py` and is passed through
  `tools/run_question_ingest_skill.py` only when enabled. The 2026-07-21
  47-question run enabled the fallback switch, but the observed prepared-job
  records have `mineru_fallback=null`; no actual MinerU output files were
  retained in that run's `_mineru_fallback` directory.
- `split_v03` declares Runtime import and database writes disabled by default.
- Visual/model provider is explicit and gated by API key when using
  `--provider visual`.
- Final-chain-specific `pdf_math` ownership is not yet modeled separately.

Current primary node selection:

- Orchestrator: `tools/run_question_ingest_skill.py`
- Image need gate: `tools/model_image_need_gate.py`
- Candidate split: `tools/build_figure_candidate_source.py`
- Visual transcription: `tools/teacher_handout_visual_transcribe_doubao.py`
- Format normalize / formula patch evidence:
  `tools/apply_format_normalize_existing_results.py`,
  `tools/math_formula_library_gate.py`, `tools/katex_validate_math.cjs`
- Figure detection / visual source preparation:
  `tools/prepare_option_visual_source.py`
- Prepared source merge: `tools/merge_candidate_prepared_sources.py`
- Assetize: `tools/assetize_question_images.py`
- Visual consolidation: `tools/consolidate_visual_assets.py`
- Reconcile/refine: `tools/reconcile_and_refine_visual_assets.py`
- Package audit: `tools/audit_question_asset_package.py`

Excluded from primary-node selection unless explicitly used as regression
evidence: files or output roots whose names contain `backup`, `.bak`, `smoke`,
`probe`, or `demo`.

Local probe on 2026-07-31:

- A clean local venv with Python 3.12.10 can import the PDF/image dependencies
  needed by these nodes.
- `run_question_ingest_skill.py --help`,
  `audit_question_asset_package.py --help`, and
  `reconcile_and_refine_visual_assets.py --help` load successfully.
- `math_formula_library_gate.py` is a stdin tool rather than an argparse CLI;
  a direct stdin probe detects split macros such as `\in fty` and
  `\leq slant`.
- Re-running assetize -> consolidate -> reconcile/refine without model steps ->
  audit from the moved-machine intermediate `prepared_merged.json` executes,
  but produces 47 fails because 47 materialized source assets are missing.
  Interpretation: the retained intermediate records still depend on old
  absolute paths, so they are not portable after the machine move.
- Re-running audit directly on the retained final2 manifest succeeds and
  matches the historical result: 47 questions, 45 pass, 2 needs_review
  (`tq_017`, `tq_028`), 0 fail.
- Standalone `apply_format_normalize_existing_results.py
  --skip-if-already-normalized` still asks for an API key. The unified runner
  owns the already-normalized skip check before calling that script, so this is
  an entrypoint-hardening issue, not evidence that the 47-question package is
  bad.

### `pdf_english`

Evidence:

- `config/pipeline_registry.yaml` entry `english_text_first_v05`
- `config/english_text_first_v05.yaml`
- `tools/english_text_first_v05_pipeline.py`
- `tools/english_text_first_sidecar_graph_v01.py`
- `tests/test_english_text_first_v05_pipeline.py`
- `tests/test_english_text_first_sidecar_graph_v01.py`

Current shape:

- English Text-first v0.5 is registered as experimental and isolated.
- Portable tests use recorded fixtures and assert zero model calls.
- Runtime import and database writes are disabled.
- Output is candidate/review artifacts, not final Runtime import.
- `split_v03` also has legacy/generic English PDF support, which should not be
  treated as the same ownership boundary as English Text-first.
- The strongest retained old local package is `en_full3docs_v20_pkg_20260724.zip`.
  Later graph-first/cloze work should be treated as lineage evidence unless its
  manifest and artifacts are restored into a clean branch.

## Cross-Cutting Pipelines

`runtime_backend` is a downstream runtime validation/export surface. It is not
one of the four source-ingest final chains.

`semantic_role_shadow` is a sidecar/evaluation support pipeline. It is not one
of the four source-ingest final chains.

## Main Mismatch

The repository currently has:

- four intended final chains: `doc_math`, `doc_english`, `pdf_math`, `pdf_english`
- four registered technical pipelines: `split_v03`, `runtime_backend`,
  `semantic_role_shadow`, `english_text_first_v05`

Those are not the same abstraction layer. The next cleanup should introduce a
small final-chain inventory/registry concept so product-chain ownership does not
have to be inferred from loose script names.

## Recommended Next Work

1. Add a package-level final-chain inventory loader/validator.
2. Keep technical pipeline registry separate, but link technical pipelines to final chains.
3. Package semantic profile config and keep `tools/semantic_profile_config.py` as a compatibility wrapper.
4. Harden `src/teachbase/infrastructure/artifact_store.py` concurrent writes.
5. Only then migrate DOCX native and English Text-first in separate final-chain slices.
