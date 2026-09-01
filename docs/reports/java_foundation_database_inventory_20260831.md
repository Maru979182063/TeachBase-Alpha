# Java Foundation Database Inventory

- Baseline: `8ca1703700c22d6e13ee3b26e2b902c8d9c5a309`
- PostgreSQL: `PostgreSQL 18.4 on x86_64-windows, compiled by msvc-19.44.35226, 64-bit`
- Applied migration: `20260624_three_track_final_review_hardening.sql`
- Public tables: **43**
- Populated by deterministic startup fixtures: **31**
- Foreign keys: **22**
- JSON/JSONB columns: **20**

The inventory was produced from an isolated, disposable PostgreSQL database. It does not use a developer database or a machine-specific path as an input contract.

## Populated Tables

| Table | Rows | Columns | Primary key | Foreign keys |
|---|---:|---:|---|---:|
| `artifact` | 18 | 18 | artifact_id | 0 |
| `artifact_dependency` | 6 | 5 | artifact_dependency_id | 0 |
| `checkpoint_catalog` | 3 | 6 | catalog_id | 0 |
| `checkpoint_catalog_version` | 3 | 8 | catalog_version_id | 0 |
| `checkpoint_node` | 6 | 8 | checkpoint_node_id | 0 |
| `component` | 6 | 13 | component_id | 1 |
| `component_link` | 6 | 6 | component_link_id | 0 |
| `component_revision` | 6 | 9 | component_revision_id | 1 |
| `document` | 3 | 15 | document_id | 0 |
| `document_group` | 3 | 7 | document_group_id | 0 |
| `document_group_member` | 3 | 6 | document_group_member_id | 0 |
| `document_source` | 3 | 7 | source_id | 0 |
| `job` | 3 | 22 | job_id | 0 |
| `job_attempt` | 3 | 9 | job_attempt_id | 0 |
| `lesson` | 3 | 13 | lesson_id | 1 |
| `lesson_import` | 3 | 9 | import_id | 0 |
| `lesson_revision` | 3 | 13 | lesson_revision_id | 1 |
| `page_asset` | 3 | 10 | page_asset_id | 1 |
| `publication` | 3 | 11 | publication_id | 2 |
| `review_task` | 3 | 10 | review_task_id | 0 |
| `run` | 3 | 10 | run_id | 0 |
| `runtime_metadata` | 1 | 4 | snapshot_key | 0 |
| `source_node` | 6 | 5 | source_node_id | 0 |
| `source_node_checkpoint_link` | 4 | 7 | link_id | 0 |
| `source_node_revision` | 6 | 15 | source_node_revision_id | 0 |
| `subject_track` | 3 | 6 | track_code | 0 |
| `task` | 6 | 5 | task_id | 0 |
| `task_checkpoint_override` | 3 | 8 | override_id | 0 |
| `task_projection` | 6 | 24 | task_projection_id | 4 |
| `task_revision` | 6 | 14 | task_revision_id | 0 |
| `task_subject_ext` | 6 | 11 | task_revision_id | 2 |

## Empty Tables

`component_patch_candidate`, `document_relation`, `job_dependency`, `material_build`, `material_item`, `outbox_event`, `quality_evaluation`, `question_bank_item`, `question_bank_item_revision`, `question_bank_source_link`, `runtime_migration_warning`, `runtime_state_snapshot`

## JSON Payloads With Data

- `artifact.summary_json`: 18 values; keys: `bundle_id`, `lesson_id`, `page_no`, `lesson_revision_id`, `content_hash`, `source_node_count`, `task_count`
- `component.bbox_json`: 6 values; keys: `height`, `width`, `x`, `y`
- `component_revision.bbox_json`: 6 values; keys: `height`, `width`, `x`, `y`
- `component_revision.source_refs_json`: 6 values; keys: `page_no`
- `document.metadata_json`: 3 values; keys: no object keys
- `document_group.metadata_json`: 3 values; keys: `lesson_id`
- `document_source.metadata_json`: 3 values; keys: `bundle_id`
- `lesson_revision.bundle_jsonb`: 3 values; keys: `bundle_id`, `checkpoint_candidates`, `components`, `grade`, `lesson_id`, `lesson_revision_id`, `quality_issues`, `season`, `source_tree`, `stage`, `subject`, `subject_extensions`, `tasks`, `title`, `track_code`
- `task_projection.source_refs_json`: 6 values; keys: `component_id`, `crop_artifact_id`, `page_no`
- `task_subject_ext.payload_json`: 6 values; keys: `component_kind`, `difficulty_confidence`, `difficulty_level`, `difficulty_scheme`, `difficulty_source`, `source_refs_json`, `tags`, `track_code`

## Relationship Risk

There are **79** identifier-like columns without a database foreign key. This is a heuristic list, not proof that every column needs an FK. It is the main input for the field mapping review.

- `artifact.run_id`
- `artifact.job_id`
- `artifact.supersedes_artifact_id`
- `artifact_dependency.parent_artifact_id`
- `artifact_dependency.child_artifact_id`
- `checkpoint_catalog_version.catalog_id`
- `checkpoint_catalog_version.base_version_id`
- `checkpoint_catalog_version.overlay_ref`
- `checkpoint_node.catalog_version_id`
- `checkpoint_node.parent_id`
- `component.parent_component_id`
- `component.crop_artifact_id`
- `component.current_revision_id`
- `component_link.target_revision_id`
- `component_patch_candidate.base_component_revision_id`
- `component_patch_candidate.proposed_component_revision_id`
- `component_patch_candidate.target_task_revision_id`
- `component_patch_candidate.run_id`
- `component_patch_candidate.accepted_lesson_revision_id`
- `component_revision.source_task_revision_id`
- `document.source_id`
- `document_group_member.document_group_id`
- `document_relation.from_document_id`
- `document_relation.to_document_id`
- `document_source.owner_id`
- `document_source.import_batch_id`
- `job.run_id`
- `job.error_detail_ref`
- `job.payload_ref`
- `job.result_artifact_id`
- `job_attempt.job_id`
- `job_attempt.worker_ref`
- `job_dependency.upstream_job_id`
- `job_dependency.downstream_job_id`
- `lesson.document_group_id`
- `lesson.active_revision_id`
- `lesson.published_revision_id`
- `lesson_import.bundle_id`
- `lesson_import.run_id`
- `lesson_import.review_task_id`
- `lesson_import.artifact_id`
- `lesson_revision.base_artifact_id`
- `lesson_revision.generated_snapshot_ref`
- `lesson_revision.manual_patch_ref`
- `lesson_revision.merged_snapshot_ref`
- `outbox_event.aggregate_id`
- `page_asset.image_artifact_id`
- `page_asset.ocr_artifact_id`
- `page_asset.layout_artifact_id`
- `publication.published_artifact_id`
- `publication.superseded_by_publication_id`
- `quality_evaluation.target_revision_id`
- `quality_evaluation.evidence_ref`
- `question_bank_item.current_revision_id`
- `question_bank_source_link.local_task_id`
- `question_bank_source_link.source_node_local_id`
- `review_task.target_revision_id`
- `review_task.run_id`
- `run.root_target_id`
- `runtime_migration_warning.entity_id`
- `source_node.current_revision_id`
- `source_node_checkpoint_link.source_node_revision_id`
- `source_node_checkpoint_link.checkpoint_node_id`
- `source_node_revision.source_node_id`
- `source_node_revision.parent_node_revision_id`
- `source_node_revision.component_bundle_ref`
- `source_node_revision.generated_data_ref`
- `source_node_revision.manual_patch_ref`
- `source_node_revision.merged_data_ref`
- `task.current_revision_id`
- `task_checkpoint_override.task_revision_id`
- `task_checkpoint_override.checkpoint_node_id`
- `task_projection.local_task_id`
- `task_projection.source_node_local_id`
- `task_revision.task_id`
- `task_revision.source_node_revision_id`
- `task_revision.generated_data_ref`
- `task_revision.manual_patch_ref`
- `task_revision.merged_data_ref`

