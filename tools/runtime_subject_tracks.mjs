/**
 * 用途：
 * - 集中维护验证版三轨学科配置，避免后端各处各写一份判断。
 * - 轨道、学科、学段和难度归一化规则统一从这里发散。
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const workspaceRoot = path.resolve(__dirname, "..");
const trackConfigPath = path.join(workspaceRoot, "config", "subject_tracks.json");

let cachedTrackConfig = null;

function loadTrackConfig() {
  if (!cachedTrackConfig) {
    cachedTrackConfig = JSON.parse(fs.readFileSync(trackConfigPath, "utf8"));
  }
  return cachedTrackConfig;
}

function normalizeText(value) {
  return String(value || "")
    .trim()
    .toLowerCase();
}

function normalizeGrade(value) {
  const normalized = normalizeText(value).replace(/^grade[_\s-]*/u, "g");
  const chineseMapping = new Map([
    ["初一", "g7"],
    ["初二", "g8"],
    ["初三", "g9"],
    ["高一", "g10"],
    ["高二", "g11"],
    ["高三", "g12"],
  ]);
  return chineseMapping.get(normalized) || normalized;
}

export function listTrackProfiles() {
  return Object.values(loadTrackConfig().tracks || {});
}

export function getTrackProfile(trackCode) {
  return loadTrackConfig().tracks?.[trackCode] || null;
}

function matchesAlias(candidate, aliases = []) {
  const normalizedCandidate = normalizeText(candidate);
  return aliases.some((alias) => normalizeText(alias) === normalizedCandidate);
}

export function resolveTrackCode(input = {}) {
  const explicitTrackCode = input.track_code || input.trackCode || "";
  if (explicitTrackCode) {
    const explicitProfile = getTrackProfile(explicitTrackCode);
    if (!explicitProfile) {
      throw new Error(`track_profile_not_found:${explicitTrackCode}`);
    }
    return explicitProfile.track_code;
  }

  const subject = input.subject || "";
  const stage = input.stage || "";
  const grade = input.grade || "";
  const profiles = listTrackProfiles().filter((profile) => {
    if (subject && !matchesAlias(subject, [profile.subject, ...(profile.subject_aliases || [])])) {
      return false;
    }
    if (stage && !matchesAlias(stage, [profile.stage, ...(profile.stage_aliases || [])])) {
      return false;
    }
    if (grade) {
      const normalizedGrade = normalizeGrade(grade);
      const aliases = (profile.grade_aliases || []).map(normalizeGrade);
      if (aliases.length > 0 && !aliases.includes(normalizedGrade)) {
        return false;
      }
    }
    return true;
  });

  if (profiles.length === 1) {
    return profiles[0].track_code;
  }
  if (profiles.length === 0) {
    throw new Error(
      `track_profile_not_found:${subject || "unknown_subject"}:${stage || "unknown_stage"}:${grade || "unknown_grade"}`
    );
  }
  throw new Error(
    `track_profile_ambiguous:${subject || "unknown_subject"}:${stage || "unknown_stage"}:${grade || "unknown_grade"}`
  );
}

export function resolveTrackProfile(input = {}) {
  const trackCode = resolveTrackCode(input);
  return getTrackProfile(trackCode);
}

export function validateTrackProfile(input = {}) {
  const profile = resolveTrackProfile(input);
  if (
    input.subject &&
    !matchesAlias(input.subject, [profile.subject, ...(profile.subject_aliases || [])])
  ) {
    throw new Error(`track_subject_mismatch:${profile.track_code}`);
  }
  if (
    input.stage &&
    !matchesAlias(input.stage, [profile.stage, ...(profile.stage_aliases || [])])
  ) {
    throw new Error(`track_stage_mismatch:${profile.track_code}`);
  }
  return profile;
}

export function normalizeDifficultyLevel(value, fallback = 3) {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.min(5, Math.max(1, Math.round(value)));
  }

  const text = String(value).trim();
  if (/^[1-5]$/.test(text)) {
    return Number(text);
  }

  const normalized = normalizeText(text);
  const mapping = new Map([
    ["低风险", 2],
    ["中风险", 3],
    ["高风险", 4],
    ["easy", 2],
    ["medium", 3],
    ["hard", 4],
    ["unknown", fallback],
  ]);
  return mapping.get(normalized) || fallback;
}

export function normalizeDifficultyConfidence(value, fallback = 0.8) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  return Math.max(0, Math.min(1, numeric));
}

export function normalizeDifficultyPayload(input = {}, options = {}) {
  return {
    difficulty_level: normalizeDifficultyLevel(
      input.difficulty_level ?? input.difficultyLevel ?? input.risk,
      options.defaultLevel ?? 3
    ),
    difficulty_scheme:
      input.difficulty_scheme ||
      input.difficultyScheme ||
      options.defaultScheme ||
      "difficulty.manual.v1",
    difficulty_source:
      input.difficulty_source ||
      input.difficultySource ||
      options.defaultSource ||
      "manual",
    difficulty_confidence: normalizeDifficultyConfidence(
      input.difficulty_confidence ?? input.difficultyConfidence,
      options.defaultConfidence ?? 0.8
    ),
  };
}
