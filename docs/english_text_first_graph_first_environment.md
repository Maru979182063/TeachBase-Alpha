# English Text First Graph First Environment

## Real Status

`english_text_first_graph_first` is now the only named active environment for the English image-PDF text-first / graph-first review chain.

This does not mean production-ready. It means the current confirmed run lineage is pinned in one manifest so future runs, packages, and audits do not pick random `full`, `backup`, `probe`, or `badcase` directories.

## Active Manifest

- `config/english_text_first_graph_first/active_manifest.json`

The manifest currently pins the `source_surfaces / v19` branch and confirms the chain only through Node6b.

It also includes a same-level `cloze` review-candidate branch for `高考一轮完形填空之词性策略1-教师版.pdf`, limited to pages 1-8. This cloze branch is manifest-pinned for lineage control, but it is not a full-PDF production confirmation.

## Family Configs

- reading / grammar / writing: `config/english_text_first_v02.yaml`
- cloze: `config/english_text_first_graph_first/family_configs/english_text_first_v02.cloze_pos_strategy1.json`

Historical cloze configs under `outputs/english_text_first_graph_first/cloze_pos_strategy_probe_20260728/` are retained as artifacts only; do not use them as final-chain entrypoints.

## Confirmed Nodes

- Node1 VLM transcriber:
  - reading: `node1a_full_reading_38p_20260724`
  - grammar: `node1a_full_grammar_24p_20260724`
  - writing: `node1a_full_writing_21p_20260724`
  - cloze: `node1a_cloze_pos_strategy1_p001_p008_20260728`
- Node1b block attribute tagger:
  - reading: `node1b_full_reading_38p_20260724`
  - grammar: `node1b_full_grammar_24p_20260724`
  - writing: `node1b_full_writing_21p_20260724`
  - cloze: `node1b_cloze_pos_strategy1_p001_p008_20260728`
- Node2 sliding window composer:
  - reading: `node2_full_reading_38p_20260724`
  - grammar: `node2_full_grammar_24p_20260724`
  - writing: `node2_full_writing_21p_20260724`
  - cloze: `node2_cloze_pos_strategy1_p001_p008_20260728`
- Node2d document group deduper:
  - reading: `node2d_full_reading_38p_20260724`
  - grammar: `node2d_full_grammar_24p_20260724`
  - writing: `node2d_full_writing_21p_20260724`
  - cloze: `node2d_cloze_pos_strategy1_p001_p008_20260728`
  - note: Node2d original artifacts do not contain `run_summary.json`; this environment uses sidecar summaries under `outputs/english_text_first_graph_first/node2_node2d_selection_20260727/` only for manifest validation.
- Node3 group normalizer:
  - reading: `node3_full_reading_38p_20260724`
  - grammar: `node3_full_grammar_24p_20260724`
  - writing: `node3_full_writing_21p_20260724`
  - cloze: `node3_cloze_pos_strategy1_p001_p008_20260728`
- Node3b group relation resolver:
  - reading: `node3b_full_reading_38p_20260724`
  - grammar: `node3b_full_grammar_24p_20260724`
  - writing: `node3b_full_writing_21p_20260724`
  - cloze: `node3b_cloze_pos_strategy1_p001_p008_20260728`
- Node3c ownership reconciler:
  - reading: `node3c_full_reading_38p_20260724`
  - grammar: `node3c_full_grammar_24p_20260724`
  - writing: `node3c_full_writing_21p_20260724`
  - cloze: `node3c_cloze_pos_strategy1_p001_p008_20260728`
  - note: Node3c is deterministic. Its artifacts contain all groups, while `adjusted_group_count` only reports groups whose projection refs changed.
- Node4 source-backed draft builder:
  - reading: `node4_full_reading_38p_20260724`
  - grammar: `node4_full_grammar_24p_20260724`
  - writing: `node4_full_writing_21p_20260724`
  - cloze: `node4_cloze_pos_strategy1_p001_p008_20260728`
- Node5 packet builder:
  - reading: `node5_v02_source_surfaces_full_reading_20260724`
  - grammar: `node5_v02_source_surfaces_full_grammar_20260724`
  - writing: `node5_v02_source_surfaces_full_writing_20260724`
  - cloze: `node5_cloze_pos_strategy1_p001_p008_20260728`
- Node5b refiner:
  - reading: `node5b_v13_source_surfaces_full_reading_combined40_20260724`
  - grammar: `node5b_v12_source_surfaces_full_grammar_combined54_20260724`
  - writing: `node5b_v12_source_surfaces_full_writing_20260724`
  - cloze: `node5b_cloze_pos_strategy1_gloss_end_v07_p001_p008_20260728`
- Node6a projection planner:
  - reading: `node6a_v02_source_surfaces_full_reading_20260724`
  - grammar: `node6a_v02_source_surfaces_full_grammar_20260724`
  - writing: `node6a_v02_source_surfaces_full_writing_20260724`
  - cloze: `node6a_cloze_pos_strategy1_after_5b_v07_p001_p008_20260728`
- Node6b render normalizer:
  - reading: `node6b_v19_source_surfaces_full_reading_20260724`
  - grammar: `node6b_v19_source_surfaces_full_grammar_20260724`
  - writing: `node6b_v19_source_surfaces_full_writing_20260724`
  - cloze: `node6b_cloze_pos_strategy1_specialized_v05_after_5b_v07_p001_p008_20260728`

## Explicitly Not Confirmed

- Node6d is not yet pinned as the active final gate for this environment.
- The accidental `node5_full_* -> node5b_full_* -> node6b_full_*` rerun is not part of this environment.
- Runtime import and database writes are disabled.
- Cloze is pinned only for pages 1-8; the remaining pages of the source PDF have not been run through the final environment.

## Validation

Run:

```powershell
python tools\english_text_first_graph_first_manifest_check.py
```

The validator checks:

- manifest schema/name/version;
- every pinned summary and artifact exists;
- source page image counts match the manifest;
- pinned run ids do not contain forbidden fragments such as `backup`, `probe`, `smoke`, or plain `node5_full_` / `node6b_full_`;
- summary doc ids and record counts are consistent where available.
