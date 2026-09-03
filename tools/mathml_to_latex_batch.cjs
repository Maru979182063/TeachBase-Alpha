const fs = require("fs");
const path = require("path");

function resolveConverter() {
  const candidates = [];
  if (process.env.MATHML_TO_LATEX_NODE_MODULE_DIR) {
    candidates.push(process.env.MATHML_TO_LATEX_NODE_MODULE_DIR);
  }
  candidates.push(process.cwd());

  for (const base of candidates) {
    try {
      const resolved = require.resolve("mathml-to-latex", { paths: [base] });
      return require(resolved).MathMLToLaTeX;
    } catch (_error) {
      // Try the next configured module directory.
    }
  }
  return null;
}

function cleanLatex(value) {
  if (!value) return value;
  return normalizeSpacedFunctionChars(mergeNumericFragments(String(value))).split(/\s+/).filter(Boolean).join(" ").trim();
}

function normalizationActions(raw, clean) {
  const actions = [];
  if (!raw || raw === clean) return actions;
  if (/\d\s+\d/.test(raw) || /\d\s+\.\s*\d/.test(raw)) {
    actions.push("merge_numeric_fragments");
  }
  if (containsSpacedFunction(raw)) {
    actions.push("normalize_spaced_math_function_tokens");
  }
  if (!actions.length) actions.push("normalize_latex_whitespace");
  return actions;
}

function containsSpacedFunction(value) {
  return [
    "s i n",
    "c o s",
    "t a n",
    "c o t",
    "s e c",
    "c s c",
    "l o g",
    "l n",
    "e x p",
    "a r c s i n",
    "a r c c o s",
    "a r c t a n"
  ].some((item) => value.includes(item));
}

function mergeNumericFragments(value) {
  const chars = Array.from(value);
  let out = "";
  for (let i = 0; i < chars.length; i += 1) {
    const prev = out[out.length - 1] || "";
    const cur = chars[i];
    const next = chars[i + 1] || "";
    if (cur === " " && isDigit(prev) && isDigit(next)) continue;
    if (cur === " " && isDigit(prev) && next === "." && isDigit(chars[i + 2] || "")) continue;
    if (cur === "." && out.endsWith(" ") && isDigit(out[out.length - 2] || "") && isDigit(next)) {
      out = out.slice(0, -1) + ".";
      continue;
    }
    if (cur === " " && prev === "." && isDigit(next)) continue;
    out += cur;
  }
  return out;
}

function isDigit(ch) {
  return ch >= "0" && ch <= "9";
}

function normalizeSpacedFunctionChars(value) {
  const functions = ["arcsin", "arccos", "arctan", "sin", "cos", "tan", "cot", "sec", "csc", "log", "ln", "exp"];
  let out = "";
  for (let i = 0; i < value.length;) {
    let matched = "";
    let end = i;
    for (const name of functions) {
      const candidateEnd = matchSpacedName(value, i, name);
      if (candidateEnd > i && isFunctionBoundary(value, i, candidateEnd)) {
        matched = name;
        end = candidateEnd;
        break;
      }
    }
    if (matched) {
      out += "\\" + matched;
      i = end;
      continue;
    }
    out += value[i];
    i += 1;
  }
  return out;
}

function matchSpacedName(value, start, name) {
  let j = start;
  for (let index = 0; index < name.length; index += 1) {
    if (value[j] !== name[index]) return -1;
    j += 1;
    if (index < name.length - 1) {
      if (value[j] !== " ") return -1;
      while (value[j] === " ") j += 1;
    }
  }
  return j;
}

function isFunctionBoundary(value, start, end) {
  const before = value[start - 1] || "";
  const after = value[end] || "";
  if (before === "\\") return false;
  if (isLowerAscii(before)) return false;
  if (isLowerAscii(after)) return false;
  return true;
}

function isLowerAscii(ch) {
  return ch >= "a" && ch <= "z";
}

const inputPath = process.argv[2];
if (!inputPath || !fs.existsSync(inputPath)) {
  console.error("usage: node mathml_to_latex_batch.cjs mathml_batch.json");
  process.exit(2);
}

const converter = resolveConverter();
const input = JSON.parse(fs.readFileSync(inputPath, "utf8"));
const records = [];

for (const item of input.records || []) {
  const record = {
    ole_rid: item.ole_rid,
    ole_object: item.ole_object,
    status: item.status,
    latex: null,
    latex_clean: null,
    error: item.error || null
  };
  if (item.status !== "mathml_ok") {
    records.push(record);
    continue;
  }
  if (!converter) {
    record.status = "mathml_ok_latex_converter_missing";
    record.error = "Node module mathml-to-latex is not resolvable from cwd or MATHML_TO_LATEX_NODE_MODULE_DIR.";
    records.push(record);
    continue;
  }
  try {
    record.latex = converter.convert(item.mathml);
    record.latex_clean = cleanLatex(record.latex);
    record.normalization_actions = normalizationActions(record.latex, record.latex_clean);
    record.status = record.latex_clean ? "latex_ok" : "latex_empty";
  } catch (error) {
    record.status = "mathml_to_latex_failed";
    record.error = error && error.message ? error.message : String(error);
  }
  records.push(record);
}

process.stdout.write(JSON.stringify({
  schema_version: "docx_legacy_mtef_latex_batch.v0.1",
  backend: "node:mathml-to-latex",
  converter_available: Boolean(converter),
  records
}, null, 2));
