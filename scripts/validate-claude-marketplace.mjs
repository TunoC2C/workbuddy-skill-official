#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const repoRoot = process.cwd();
const sourceMarketplacePath = ".codebuddy-skill/marketplace.json";
const claudeMarketplacePath = ".claude-plugin/marketplace.json";
const codebuddyPluginMarketplacePath = ".codebuddy-plugin/marketplace.json";
const expectedMarketplaceName = "workbuddy-skills-official";

function repoPath(...segments) {
  return path.join(repoRoot, ...segments);
}

function readJson(relativePath) {
  return JSON.parse(fs.readFileSync(repoPath(relativePath), "utf8"));
}

function frontmatterField(skillSource, fieldName) {
  const skillFile = repoPath("skills", skillSource, "SKILL.md");
  const body = fs.readFileSync(skillFile, "utf8");
  const match = body.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!match) {
    return undefined;
  }

  const prefix = `${fieldName}:`;
  const line = match[1].split(/\r?\n/).find((item) => item.trimStart().startsWith(prefix));
  if (!line) {
    return undefined;
  }

  // 校验脚本与生成脚本使用同一条单行 frontmatter 读取规则，避免测试口径漂移。
  return line
    .slice(line.indexOf(":") + 1)
    .trim()
    .replace(/^["']|["']$/g, "");
}

function assertEqual(issues, label, actual, expected) {
  if (actual !== expected) {
    issues.push(`${label}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

function preferredDescription(skill) {
  // Claude 列表面向中文用户展示，优先使用人工维护的中文短描述。
  return skill.description_zh || skill.description || "";
}

function preferredDisplayName(skill) {
  // displayName 必须严格来自源 marketplace 的 name 字段，避免生成器自行改写展示名。
  return skill.name;
}

function expectedPluginEntry(skill) {
  return {
    name: skill.source,
    source: `./plugins/${skill.source}`,
    displayName: preferredDisplayName(skill),
    description: preferredDescription(skill),
  };
}

function expectedPluginManifest(skill) {
  const manifest = {
    name: skill.source,
    displayName: preferredDisplayName(skill),
    description: preferredDescription(skill),
    author: {
      name: "CodeBuddy",
    },
    skills: [
      `./skills/${skill.source}`,
    ],
  };

  const version =
    typeof skill.version === "string" && skill.version.trim() !== ""
      ? skill.version.trim()
      : frontmatterField(skill.source, "version");

  // version 缺失时只读 SKILL.md frontmatter，仍缺失则接受 Claude warning，不伪造发布版本。
  if (version) {
    manifest.version = version;
  }

  const keywords = [
    ...(Array.isArray(skill.tags_zh) ? skill.tags_zh : []),
    ...(Array.isArray(skill.tags_en) ? skill.tags_en : []),
  ].filter((value) => typeof value === "string" && value.trim() !== "");

  if (keywords.length > 0) {
    manifest.keywords = [...new Set(keywords)];
  }

  return manifest;
}

function indexByName(items) {
  const result = new Map();
  for (const item of items) {
    result.set(item.name, item);
  }
  return result;
}

function comparePluginEntry(issues, prefix, actual, expected) {
  assertEqual(issues, `${prefix}.name`, actual?.name, expected.name);
  assertEqual(issues, `${prefix}.source`, actual?.source, expected.source);
  assertEqual(issues, `${prefix}.displayName`, actual?.displayName, expected.displayName);
  assertEqual(issues, `${prefix}.description`, actual?.description, expected.description);
}

function compareManifest(issues, prefix, actual, expected) {
  assertEqual(issues, `${prefix}.name`, actual?.name, expected.name);
  assertEqual(issues, `${prefix}.displayName`, actual?.displayName, expected.displayName);
  assertEqual(issues, `${prefix}.description`, actual?.description, expected.description);
  assertEqual(issues, `${prefix}.author.name`, actual?.author?.name, expected.author.name);
  assertEqual(issues, `${prefix}.skills[0]`, actual?.skills?.[0], expected.skills[0]);

  // version 和 keywords 仅在源数据存在时校验，避免要求所有旧 skill 补齐元数据。
  if (expected.version) {
    assertEqual(issues, `${prefix}.version`, actual?.version, expected.version);
  }
  if (expected.keywords) {
    assertEqual(
      issues,
      `${prefix}.keywords`,
      JSON.stringify(actual?.keywords ?? []),
      JSON.stringify(expected.keywords),
    );
  }
}

function validateMarketplaceFile(issues, relativePath, sourceSkills) {
  if (!fs.existsSync(repoPath(relativePath))) {
    issues.push(`missing marketplace file: ${relativePath}`);
    return;
  }

  const marketplace = readJson(relativePath);
  assertEqual(issues, `${relativePath}.name`, marketplace.name, expectedMarketplaceName);
  assertEqual(issues, `${relativePath}.plugins.length`, marketplace.plugins?.length, sourceSkills.length);

  const pluginEntries = indexByName(Array.isArray(marketplace.plugins) ? marketplace.plugins : []);
  for (const skill of sourceSkills) {
    // 逐个比对 source/name/copy 文案，确保 Claude 安装 ID 不会被中文名污染。
    const expected = expectedPluginEntry(skill);
    comparePluginEntry(issues, `${relativePath}.plugins.${skill.source}`, pluginEntries.get(skill.source), expected);
  }
}

function validatePluginDirectories(issues, sourceSkills) {
  for (const skill of sourceSkills) {
    const pluginRoot = repoPath("plugins", skill.source);
    const copiedSkillFile = repoPath("plugins", skill.source, "skills", skill.source, "SKILL.md");
    const claudeManifestPath = repoPath("plugins", skill.source, ".claude-plugin", "plugin.json");
    const codebuddyManifestPath = repoPath("plugins", skill.source, ".codebuddy-plugin", "plugin.json");

    if (!fs.existsSync(pluginRoot)) {
      issues.push(`missing plugin directory: plugins/${skill.source}`);
      continue;
    }
    if (!fs.existsSync(copiedSkillFile)) {
      issues.push(`missing copied skill: plugins/${skill.source}/skills/${skill.source}/SKILL.md`);
    }
    if (!fs.existsSync(claudeManifestPath)) {
      issues.push(`missing Claude manifest: plugins/${skill.source}/.claude-plugin/plugin.json`);
      continue;
    }
    if (!fs.existsSync(codebuddyManifestPath)) {
      issues.push(`missing CodeBuddy manifest: plugins/${skill.source}/.codebuddy-plugin/plugin.json`);
    }

    // 两套 manifest 使用同一份标准字段，便于 Claude 与参考仓库的生成器互通。
    const expected = expectedPluginManifest(skill);
    compareManifest(issues, `plugins/${skill.source}/.claude-plugin/plugin.json`, readJson(path.relative(repoRoot, claudeManifestPath)), expected);
    if (fs.existsSync(codebuddyManifestPath)) {
      compareManifest(issues, `plugins/${skill.source}/.codebuddy-plugin/plugin.json`, readJson(path.relative(repoRoot, codebuddyManifestPath)), expected);
    }
  }
}

function main() {
  const sourceMarketplace = readJson(sourceMarketplacePath);
  const sourceSkills = Array.isArray(sourceMarketplace.skills) ? sourceMarketplace.skills : [];
  const issues = [];

  assertEqual(issues, `${sourceMarketplacePath}.skills.length`, sourceSkills.length > 0, true);
  validateMarketplaceFile(issues, claudeMarketplacePath, sourceSkills);
  validateMarketplaceFile(issues, codebuddyPluginMarketplacePath, sourceSkills);
  validatePluginDirectories(issues, sourceSkills);

  if (issues.length > 0) {
    const visibleIssues = issues.slice(0, 40);
    for (const issue of visibleIssues) {
      console.error(`issue: ${issue}`);
    }
    if (issues.length > visibleIssues.length) {
      console.error(`... ${issues.length - visibleIssues.length} more issue(s)`);
    }
    process.exitCode = 1;
    return;
  }

  console.log(`validated ${sourceSkills.length} Claude plugin wrapper(s)`);
}

main();
