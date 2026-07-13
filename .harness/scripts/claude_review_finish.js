#!/usr/bin/env node
/* eslint-disable no-console */
/**
 * Extract a Claude Code review result, enforce VERDICT, and optionally comment on
 * the pull request. Supports both Claude execution_file JSON/JSONL and a direct
 * review file for skipped passes.
 */
const fs = require("fs");
const { spawnSync } = require("child_process");

function usage() {
  console.error(`Usage:
  node scripts/claude_review_finish.js --pass <quality|security|performance|dependency> (--execution-file <file>|--review-file <file>)`);
}

const args = process.argv.slice(2);
let passName = "";
let executionFile = "";
let reviewFile = "";

for (let i = 0; i < args.length; i += 1) {
  const arg = args[i];
  if (arg === "--pass") passName = args[++i] || "";
  else if (arg === "--execution-file") executionFile = args[++i] || "";
  else if (arg === "--review-file") reviewFile = args[++i] || "";
  else if (arg === "-h" || arg === "--help") {
    usage();
    process.exit(0);
  } else {
    console.error(`Unknown option: ${arg}`);
    usage();
    process.exit(2);
  }
}

if (!["quality", "security", "performance", "dependency"].includes(passName)) {
  console.error("::error::Missing or invalid --pass.");
  usage();
  process.exit(2);
}
if (!executionFile && !reviewFile) {
  console.error("::error::Provide --execution-file or --review-file.");
  usage();
  process.exit(2);
}

function stripAnsi(text) {
  return text.replace(/\u001b\[[0-9;]*m/g, "");
}

function readText(file) {
  if (!file || !fs.existsSync(file)) {
    console.error(`::error::File not found: ${file}`);
    process.exit(2);
  }
  return fs.readFileSync(file, "utf8");
}

function collectClaudeText(node, out = []) {
  if (!node) return out;
  if (typeof node === "string") {
    out.push(node);
    return out;
  }
  if (Array.isArray(node)) {
    node.forEach((item) => collectClaudeText(item, out));
    return out;
  }
  if (typeof node !== "object") return out;

  if (typeof node.result === "string") out.push(node.result);
  if (typeof node.final_message === "string") out.push(node.final_message);
  if (typeof node.text === "string") out.push(node.text);

  const message = node.message;
  if (message && Array.isArray(message.content)) {
    message.content.forEach((part) => {
      if (part && typeof part.text === "string") out.push(part.text);
    });
  }
  if (Array.isArray(node.content)) {
    node.content.forEach((part) => {
      if (typeof part === "string") out.push(part);
      else if (part && typeof part.text === "string") out.push(part.text);
    });
  }

  Object.entries(node).forEach(([key, value]) => {
    if (["result", "final_message", "text", "message", "content"].includes(key)) return;
    collectClaudeText(value, out);
  });
  return out;
}

function extractFromExecutionFile(file) {
  const raw = readText(file);
  const trimmed = raw.trim();
  if (!trimmed) return "";

  try {
    const parsed = JSON.parse(trimmed);
    return collectClaudeText(parsed).filter(Boolean).join("\n\n").trim();
  } catch (_err) {
    // Continue with JSONL/plain-text parsing.
  }

  const chunks = [];
  trimmed.split(/\r?\n/).forEach((line) => {
    const s = line.trim();
    if (!s) return;
    try {
      chunks.push(...collectClaudeText(JSON.parse(s)));
    } catch (_err) {
      chunks.push(s);
    }
  });
  return chunks.filter(Boolean).join("\n\n").trim();
}

let reviewBody = reviewFile ? readText(reviewFile) : extractFromExecutionFile(executionFile);
reviewBody = stripAnsi(reviewBody).trim();

if (!reviewBody) {
  console.error("::error::Claude Code review produced no readable output.");
  process.exit(2);
}

let verdict = "";
const lines = reviewBody.split(/\r?\n/).reverse();
for (const line of lines) {
  const upper = line.trim().toUpperCase();
  if (upper.startsWith("VERDICT:")) {
    if (upper.includes("BLOCK")) verdict = "BLOCK";
    else if (upper.includes("PASS")) verdict = "PASS";
    break;
  }
}

if (!verdict) {
  console.error("::error::Claude Code review output is missing VERDICT: PASS|BLOCK.");
  console.error(reviewBody.split(/\r?\n/).slice(0, 120).join("\n"));
  process.exit(2);
}

const outFile = process.env.AI_REVIEW_OUTPUT_FILE || `claude-review-${passName}.md`;
fs.writeFileSync(outFile, `${reviewBody}\n`, "utf8");

console.log(`--- ${passName} verdict: ${verdict} ---`);
console.log(reviewBody.split(/\r?\n/).slice(0, 160).join("\n"));

const pr = process.env.PR_NUMBER || "";
const repo = process.env.GITHUB_REPOSITORY || "";
const token = process.env.GITHUB_TOKEN || "";
if (pr && repo && token) {
  const header =
    verdict === "PASS"
      ? `✅ **Claude Code Review · ${passName} · PASS**`
      : `🛑 **Claude Code Review · ${passName} · BLOCK**`;
  let body = `${header}\n\n${reviewBody}`;
  if (body.length > 60000) {
    body = `${body.slice(0, 59000)}\n\n[...review truncated for GitHub comment size...]`;
  }
  const commentFile = `${process.env.RUNNER_TEMP || process.cwd()}/claude-review-${passName}-comment.md`;
  fs.writeFileSync(commentFile, body, "utf8");
  spawnSync("gh", ["pr", "comment", pr, "--repo", repo, "--body-file", commentFile], {
    env: { ...process.env, GH_TOKEN: token },
    stdio: "ignore",
  });
}

process.exit(verdict === "BLOCK" ? 1 : 0);
