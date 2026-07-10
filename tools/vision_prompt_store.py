from __future__ import annotations

from functools import lru_cache
from pathlib import Path


PROMPT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "teacher_handout_visual_prompts.yaml"


class PromptConfigError(ValueError):
    pass


def _parse_scalar(raw: str) -> object:
    text = raw.strip()
    if not text:
        return ""
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        return text[1:-1]
    if text.startswith("'") and text.endswith("'") and len(text) >= 2:
        return text[1:-1]
    if text == "true":
        return True
    if text == "false":
        return False
    if text == "null":
        return None
    return text


def _parse_block(lines: list[str], start: int, indent: int) -> tuple[str, int]:
    block_lines: list[str] = []
    idx = start
    block_indent: int | None = None
    while idx < len(lines):
        raw = lines[idx]
        stripped = raw.strip()
        current_indent = len(raw) - len(raw.lstrip(" "))

        if stripped == "":
            if block_indent is None:
                block_lines.append("")
            else:
                block_lines.append("")
            idx += 1
            continue

        if current_indent <= indent:
            break

        if block_indent is None:
            block_indent = current_indent

        if current_indent < block_indent:
            break

        block_lines.append(raw[block_indent:])
        idx += 1

    return "\n".join(block_lines).rstrip("\n"), idx


def _parse_mapping(lines: list[str], start: int, indent: int) -> tuple[dict[str, object], int]:
    result: dict[str, object] = {}
    idx = start
    while idx < len(lines):
        raw = lines[idx]
        stripped = raw.strip()

        if stripped == "" or stripped.startswith("#"):
            idx += 1
            continue

        current_indent = len(raw) - len(raw.lstrip(" "))
        if current_indent < indent:
            break
        if current_indent > indent:
            raise PromptConfigError(f"invalid_indentation_at_line_{idx + 1}")

        if ":" not in stripped:
            raise PromptConfigError(f"missing_colon_at_line_{idx + 1}")

        key, rest = stripped.split(":", 1)
        key = key.strip()
        rest = rest.strip()

        if rest == "|":
            value, idx = _parse_block(lines, idx + 1, current_indent)
        elif rest == "":
            value, idx = _parse_mapping(lines, idx + 1, current_indent + 2)
        else:
            value = _parse_scalar(rest)
            idx += 1

        result[key] = value

    return result, idx


@lru_cache(maxsize=1)
def load_prompt_config() -> dict[str, object]:
    text = PROMPT_CONFIG_PATH.read_text(encoding="utf-8")
    data, _ = _parse_mapping(text.splitlines(), 0, 0)
    return data


def render_template(template: str, replacements: dict[str, str]) -> str:
    rendered = str(template)
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered


def get_transcription_prompt_bundle(variant: str | None = None) -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    transcription = prompts.get("transcription", {})
    if not isinstance(transcription, dict):
        raise PromptConfigError("missing_transcription_prompt_config")
    variants = transcription.get("variants", {})
    if not isinstance(variants, dict):
        raise PromptConfigError("missing_transcription_variants")
    variant_name = variant or str(transcription.get("active_variant", "") or "")
    entry = variants.get(variant_name, {})
    if not isinstance(entry, dict):
        raise PromptConfigError(f"missing_transcription_variant:{variant_name}")
    return {
        "variant": variant_name,
        "prompt_version": str(entry.get("prompt_version", "") or ""),
        "system_prompt": str(transcription.get("system_prompt", "") or ""),
        "user_template": str(entry.get("user_template", "") or ""),
    }


def get_raw_blocks_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    raw_blocks = prompts.get("raw_blocks", {})
    if not isinstance(raw_blocks, dict):
        raise PromptConfigError("missing_raw_blocks_prompt_config")
    return {
        "prompt_version": str(raw_blocks.get("prompt_version", "") or ""),
        "system_prompt": str(raw_blocks.get("system_prompt", "") or ""),
        "user_template": str(raw_blocks.get("user_template", "") or ""),
    }


def get_field_mapping_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    field_mapping = prompts.get("field_mapping", {})
    if not isinstance(field_mapping, dict):
        raise PromptConfigError("missing_field_mapping_prompt_config")
    return {
        "prompt_version": str(field_mapping.get("prompt_version", "") or ""),
        "system_prompt": str(field_mapping.get("system_prompt", "") or ""),
        "user_template": str(field_mapping.get("user_template", "") or ""),
    }


def get_format_normalize_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    format_normalize = prompts.get("format_normalize", {})
    if not isinstance(format_normalize, dict):
        raise PromptConfigError("missing_format_normalize_prompt_config")
    return {
        "prompt_version": str(format_normalize.get("prompt_version", "") or ""),
        "system_prompt": str(format_normalize.get("system_prompt", "") or ""),
        "user_template": str(format_normalize.get("user_template", "") or ""),
    }


def get_refine_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    refine = prompts.get("refine", {})
    if not isinstance(refine, dict):
        raise PromptConfigError("missing_refine_prompt_config")
    return {
        "prompt_version": str(refine.get("prompt_version", "") or ""),
        "user_template": str(refine.get("user_template", "") or ""),
    }


def get_option_anchor_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    option_anchor = prompts.get("option_anchor", {})
    if not isinstance(option_anchor, dict):
        raise PromptConfigError("missing_option_anchor_prompt_config")
    return {
        "prompt_version": str(option_anchor.get("prompt_version", "") or ""),
        "system_prompt": str(option_anchor.get("system_prompt", "") or ""),
        "user_template": str(option_anchor.get("user_template", "") or ""),
    }


def get_inline_figure_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    inline_figure = prompts.get("inline_figure", {})
    if not isinstance(inline_figure, dict):
        raise PromptConfigError("missing_inline_figure_prompt_config")
    return {
        "prompt_version": str(inline_figure.get("prompt_version", "") or ""),
        "system_prompt": str(inline_figure.get("system_prompt", "") or ""),
        "user_template": str(inline_figure.get("user_template", "") or ""),
    }


def get_inline_figure_refine_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    inline_figure_refine = prompts.get("inline_figure_refine", {})
    if not isinstance(inline_figure_refine, dict):
        raise PromptConfigError("missing_inline_figure_refine_prompt_config")
    return {
        "prompt_version": str(inline_figure_refine.get("prompt_version", "") or ""),
        "system_prompt": str(inline_figure_refine.get("system_prompt", "") or ""),
        "user_template": str(inline_figure_refine.get("user_template", "") or ""),
    }


def get_option_figure_refine_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    option_figure_refine = prompts.get("option_figure_refine", {})
    if not isinstance(option_figure_refine, dict):
        raise PromptConfigError("missing_option_figure_refine_prompt_config")
    return {
        "prompt_version": str(option_figure_refine.get("prompt_version", "") or ""),
        "system_prompt": str(option_figure_refine.get("system_prompt", "") or ""),
        "user_template": str(option_figure_refine.get("user_template", "") or ""),
    }


def get_visual_insert_anchor_review_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    visual_insert = prompts.get("visual_insert_anchor_review", {})
    if not isinstance(visual_insert, dict):
        raise PromptConfigError("missing_visual_insert_anchor_review_prompt_config")
    return {
        "prompt_version": str(visual_insert.get("prompt_version", "") or ""),
        "system_prompt": str(visual_insert.get("system_prompt", "") or ""),
        "user_template": str(visual_insert.get("user_template", "") or ""),
    }


def get_visual_block_layout_review_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    visual_block_layout = prompts.get("visual_block_layout_review", {})
    if not isinstance(visual_block_layout, dict):
        raise PromptConfigError("missing_visual_block_layout_review_prompt_config")
    return {
        "prompt_version": str(visual_block_layout.get("prompt_version", "") or ""),
        "system_prompt": str(visual_block_layout.get("system_prompt", "") or ""),
        "user_template": str(visual_block_layout.get("user_template", "") or ""),
    }


def get_split_node_refine_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    split_node_refine = prompts.get("split_node_refine", {})
    if not isinstance(split_node_refine, dict):
        raise PromptConfigError("missing_split_node_refine_prompt_config")
    return {
        "prompt_version": str(split_node_refine.get("prompt_version", "") or ""),
        "system_prompt": str(split_node_refine.get("system_prompt", "") or ""),
        "user_template": str(split_node_refine.get("user_template", "") or ""),
    }


def get_continuation_judge_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    continuation_judge = prompts.get("continuation_judge", {})
    if not isinstance(continuation_judge, dict):
        raise PromptConfigError("missing_continuation_judge_prompt_config")
    return {
        "prompt_version": str(continuation_judge.get("prompt_version", "") or ""),
        "system_prompt": str(continuation_judge.get("system_prompt", "") or ""),
        "user_template": str(continuation_judge.get("user_template", "") or ""),
    }


def get_ownership_conflict_judge_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    ownership_conflict = prompts.get("ownership_conflict_judge", {})
    if not isinstance(ownership_conflict, dict):
        raise PromptConfigError("missing_ownership_conflict_judge_prompt_config")
    return {
        "prompt_version": str(ownership_conflict.get("prompt_version", "") or ""),
        "system_prompt": str(ownership_conflict.get("system_prompt", "") or ""),
        "user_template": str(ownership_conflict.get("user_template", "") or ""),
    }


def get_analysis_figure_rescan_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    analysis_figure_rescan = prompts.get("analysis_figure_rescan", {})
    if not isinstance(analysis_figure_rescan, dict):
        raise PromptConfigError("missing_analysis_figure_rescan_prompt_config")
    return {
        "prompt_version": str(analysis_figure_rescan.get("prompt_version", "") or ""),
        "system_prompt": str(analysis_figure_rescan.get("system_prompt", "") or ""),
        "user_template": str(analysis_figure_rescan.get("user_template", "") or ""),
    }


def get_public_figure_rescan_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    public_figure_rescan = prompts.get("public_figure_rescan", {})
    if not isinstance(public_figure_rescan, dict):
        raise PromptConfigError("missing_public_figure_rescan_prompt_config")
    return {
        "prompt_version": str(public_figure_rescan.get("prompt_version", "") or ""),
        "system_prompt": str(public_figure_rescan.get("system_prompt", "") or ""),
        "user_template": str(public_figure_rescan.get("user_template", "") or ""),
    }


def get_public_figure_route_review_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    public_figure_route_review = prompts.get("public_figure_route_review", {})
    if not isinstance(public_figure_route_review, dict):
        raise PromptConfigError("missing_public_figure_route_review_prompt_config")
    return {
        "prompt_version": str(public_figure_route_review.get("prompt_version", "") or ""),
        "system_prompt": str(public_figure_route_review.get("system_prompt", "") or ""),
        "user_template": str(public_figure_route_review.get("user_template", "") or ""),
    }


def get_image_need_gate_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    image_need_gate = prompts.get("image_need_gate", {})
    if not isinstance(image_need_gate, dict):
        raise PromptConfigError("missing_image_need_gate_prompt_config")
    return {
        "prompt_version": str(image_need_gate.get("prompt_version", "") or ""),
        "system_prompt": str(image_need_gate.get("system_prompt", "") or ""),
        "user_template": str(image_need_gate.get("user_template", "") or ""),
    }


def get_runtime_route_planner_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    runtime_route_planner = prompts.get("runtime_route_planner", {})
    if not isinstance(runtime_route_planner, dict):
        raise PromptConfigError("missing_runtime_route_planner_prompt_config")
    return {
        "prompt_version": str(runtime_route_planner.get("prompt_version", "") or ""),
        "system_prompt": str(runtime_route_planner.get("system_prompt", "") or ""),
        "user_template": str(runtime_route_planner.get("user_template", "") or ""),
    }


def get_english_unit_planner_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    english_unit_planner = prompts.get("english_unit_planner", {})
    if not isinstance(english_unit_planner, dict):
        raise PromptConfigError("missing_english_unit_planner_prompt_config")
    return {
        "prompt_version": str(english_unit_planner.get("prompt_version", "") or ""),
        "system_prompt": str(english_unit_planner.get("system_prompt", "") or ""),
        "user_template": str(english_unit_planner.get("user_template", "") or ""),
    }


def get_english_question_splitter_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    english_question_splitter = prompts.get("english_question_splitter", {})
    if not isinstance(english_question_splitter, dict):
        raise PromptConfigError("missing_english_question_splitter_prompt_config")
    return {
        "prompt_version": str(english_question_splitter.get("prompt_version", "") or ""),
        "system_prompt": str(english_question_splitter.get("system_prompt", "") or ""),
        "user_template": str(english_question_splitter.get("user_template", "") or ""),
    }


def get_english_panel_planner_prompt_bundle() -> dict[str, str]:
    config = load_prompt_config()
    prompts = config.get("prompts", {})
    if not isinstance(prompts, dict):
        raise PromptConfigError("missing_prompts_root")
    english_panel_planner = prompts.get("english_panel_planner", {})
    if not isinstance(english_panel_planner, dict):
        raise PromptConfigError("missing_english_panel_planner_prompt_config")
    return {
        "prompt_version": str(english_panel_planner.get("prompt_version", "") or ""),
        "system_prompt": str(english_panel_planner.get("system_prompt", "") or ""),
        "user_template": str(english_panel_planner.get("user_template", "") or ""),
    }
