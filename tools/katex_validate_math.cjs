const fs = require("fs");
const path = require("path");
const vm = require("vm");

const katexPath = path.join(__dirname, "..", "runtime", "html_assets_cache", "katex_js.js");
const katexCode = fs.readFileSync(katexPath, "utf8");
const sandbox = {
  module: { exports: {} },
  exports: {},
  console,
  self: {},
};
sandbox.exports = sandbox.module.exports;
vm.runInNewContext(katexCode, sandbox, { filename: katexPath });
const katex = sandbox.module.exports && sandbox.module.exports.renderToString
  ? sandbox.module.exports
  : sandbox.module.exports.default;

function readInput() {
  const raw = fs.readFileSync(0, "utf8").trim();
  if (!raw) {
    return { items: [] };
  }
  return JSON.parse(raw);
}

function validateItem(item) {
  try {
    katex.renderToString(String(item.tex || ""), {
      displayMode: Boolean(item.displayMode),
      throwOnError: true,
      strict: "warn",
      trust: false,
      maxExpand: 1000,
    });
    return {
      id: String(item.id || ""),
      ok: true,
      error: "",
      errorName: "",
      position: null,
      length: null,
      rawMessage: "",
    };
  } catch (error) {
    return {
      id: String(item.id || ""),
      ok: false,
      error: String(error && error.message ? error.message : error),
      errorName: String(error && error.name ? error.name : ""),
      position: Number.isInteger(error && error.position) ? error.position : null,
      length: Number.isInteger(error && error.length) ? error.length : null,
      rawMessage: String(error && error.rawMessage ? error.rawMessage : ""),
    };
  }
}

const input = readInput();
const items = Array.isArray(input.items) ? input.items : [];
process.stdout.write(JSON.stringify({ schema: "katex_validation_v0.1", results: items.map(validateItem) }));
