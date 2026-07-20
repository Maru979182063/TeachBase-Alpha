Plan this long composite math question.

Use only the block ids, asset ids, and text in the input.

Important:
- Preserve nested labels. If the source has (2) with ①, ②, ③ underneath it, output one parent segment for (2) and child segments for ①, ②, ③.
- If an answer block contains answers for multiple child tasks, you may map the same answer block id to multiple child segments.
- If an explanation block section contains multiple child tasks, map it to the most specific child segment when clear; otherwise map it to the parent segment.
- Images should be assigned to the segment where they are needed to read or solve that task.
- The shared stem should not absorb child task text.
- Do not include document section headers from context blocks in segments. They are upstream context, not part of this question's internal structure.

Input:
```json
{{input_json}}
```

Required output shape:
```json
{
  "schema": "docx_math_long_composite_plan_v0.1",
  "doc_id": "{{doc_id}}",
  "source_draft_id": "{{source_draft_id}}",
  "source_group_id": "{{source_group_id}}",
  "prompt_version": "{{prompt_version}}",
  "route": "long_composite",
  "segments": [
    {
      "segment_id": "stem",
      "label": "",
      "level": 0,
      "parent_id": "",
      "role": "stem",
      "question_block_ids": [],
      "answer_block_ids": [],
      "explanation_block_ids": [],
      "asset_ids": [],
      "children": []
    }
  ],
  "warnings": []
}
```
