#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const repoRoot = process.cwd();
const args = new Set(process.argv.slice(2));
const checkOnly = args.has("--check");

const sourceMarketplacePath = ".codebuddy-skill/marketplace.json";
const claudeMarketplacePath = ".claude-plugin/marketplace.json";
const codebuddyPluginMarketplacePath = ".codebuddy-plugin/marketplace.json";
const marketplaceName = "workbuddy-skills-official";
const pluginSourceRepo = "TunoC2C/workbuddy-skill-official";

function repoPath(...segments) {
  return path.join(repoRoot, ...segments);
}

function toPosixPath(value) {
  return value.replaceAll(path.sep, "/");
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

  // 这里只读取单行标量；复杂 YAML 继续留给原 SKILL.md，不在插件 manifest 里展开。
  return line
    .slice(line.indexOf(":") + 1)
    .trim()
    .replace(/^["']|["']$/g, "");
}

function jsonBody(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

function ensureDirectory(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
}

function fileBodyDiffers(filePath, body) {
  return !fs.existsSync(filePath) || fs.readFileSync(filePath, "utf8") !== body;
}

function preferredDescription(skill) {
  // Claude Code 插件列表需要短而清晰的中文说明，优先使用人工维护的 description_zh。
  return skill.description_zh || skill.description || "";
}

function preferredDisplayName(skill) {
  // displayName 严格来自源 marketplace 的 name 字段，避免生成器自行改写展示名。
  return skill.name;
}

function pluginKeywords(skill) {
  const values = [
    ...(Array.isArray(skill.tags_zh) ? skill.tags_zh : []),
    ...(Array.isArray(skill.tags_en) ? skill.tags_en : []),
  ].filter((value) => typeof value === "string" && value.trim() !== "");

  return [...new Set(values)];
}

function normalizedIdentity(value) {
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

function describeSkill(skill) {
  return skill.source || skill.name || "<unknown>";
}

function validateUniqueIdentity(issues, label, items, keyFn, describeFn) {
  const seen = new Map();

  for (const item of items) {
    const value = normalizedIdentity(keyFn(item));
    if (!value) {
      continue;
    }

    if (!seen.has(value)) {
      seen.set(value, []);
    }
    seen.get(value).push(describeFn(item));
  }

  for (const [value, matches] of seen) {
    if (matches.length > 1) {
      issues.push(`duplicate ${label}: ${value} (${matches.join(", ")})`);
    }
  }
}

function buildPluginEntry(skill) {
  return {
    name: skill.source,
    // 远程市场只保留清单；安装时按需拉取单个插件目录，避免首次添加市场时下载整个 plugins 目录。
    source: {
      source: "git-subdir",
      url: pluginSourceRepo,
      path: `plugins/${skill.source}`,
    },
    displayName: preferredDisplayName(skill),
    description: preferredDescription(skill),
  };
}

function buildPluginManifest(skill) {
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

  // 优先使用市场版本，缺失时读取 SKILL.md frontmatter，仍缺失则不伪造版本号。
  if (version) {
    manifest.version = version;
  }

  const keywords = pluginKeywords(skill);
  if (keywords.length > 0) {
    manifest.keywords = keywords;
  }

  return manifest;
}

function buildMarketplace(sourceMarketplace, plugins) {
  const ownerName = sourceMarketplace.owner?.name || "CodeBuddy";
  return {
    // Claude 安装命令使用该市场名；这里不沿用旧 CodeBuddy skill 市场名。
    name: marketplaceName,
    description: `${sourceMarketplace.description || "CodeBuddy 官方技能市场"}，适配 Claude Code 插件市场。`,
    owner: {
      name: ownerName,
    },
    plugins,
  };
}

function collectFiles(directory) {
  if (!fs.existsSync(directory)) {
    return [];
  }

  const files = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      // 递归比较源 skill 与插件副本，确保删除源文件后不会遗留过期产物。
      files.push(...collectFiles(fullPath));
      continue;
    }
    if (entry.isFile()) {
      files.push(fullPath);
    }
  }

  return files;
}

function relativeFileSet(root) {
  return new Set(collectFiles(root).map((filePath) => toPosixPath(path.relative(root, filePath))));
}

function directoriesMatch(sourceDir, targetDir) {
  if (!fs.existsSync(sourceDir) || !fs.existsSync(targetDir)) {
    return false;
  }

  const sourceFiles = relativeFileSet(sourceDir);
  const targetFiles = relativeFileSet(targetDir);
  if (sourceFiles.size !== targetFiles.size) {
    return false;
  }

  for (const relativePath of sourceFiles) {
    if (!targetFiles.has(relativePath)) {
      return false;
    }

    // 直接按字节比较文件内容，避免只看时间戳导致生成结果漂移。
    const sourceBody = fs.readFileSync(path.join(sourceDir, relativePath));
    const targetBody = fs.readFileSync(path.join(targetDir, relativePath));
    if (!sourceBody.equals(targetBody)) {
      return false;
    }
  }

  return true;
}

function mirrorSkillDirectory(sourceDir, targetDir) {
  // 目标目录是生成产物，先清空再复制可以避免源 skill 删除文件后残留旧文件。
  fs.rmSync(targetDir, { recursive: true, force: true });
  fs.mkdirSync(path.dirname(targetDir), { recursive: true });
  fs.cpSync(sourceDir, targetDir, { recursive: true });
}

function validateSourceSkills(sourceSkills) {
  const issues = [];

  // Generated plugin manifests use source as name and marketplace name as displayName.
  validateUniqueIdentity(issues, "plugin name", sourceSkills, (skill) => skill.source, describeSkill);
  validateUniqueIdentity(issues, "plugin displayName", sourceSkills, (skill) => skill.name, describeSkill);

  for (const skill of sourceSkills) {
    if (!skill.source || typeof skill.source !== "string") {
      issues.push(`skill ${JSON.stringify(skill.name)} missing source`);
      continue;
    }

    const skillFile = repoPath("skills", skill.source, "SKILL.md");
    if (!fs.existsSync(skillFile)) {
      // 每个插件都直接包装原 skill；源文件不存在时不能生成半成品插件。
      issues.push(`missing skill file: skills/${skill.source}/SKILL.md`);
    }
  }

  return issues;
}

function main() {
  const sourceMarketplace = readJson(sourceMarketplacePath);
  const sourceSkills = Array.isArray(sourceMarketplace.skills) ? sourceMarketplace.skills : [];
  const sourceIssues = validateSourceSkills(sourceSkills);
  if (sourceIssues.length > 0) {
    for (const issue of sourceIssues) {
      console.error(`issue: ${issue}`);
    }
    process.exitCode = 1;
    return;
  }

  const pluginEntries = sourceSkills.map(buildPluginEntry);
  const marketplace = buildMarketplace(sourceMarketplace, pluginEntries);
  const plannedWrites = [
    [claudeMarketplacePath, jsonBody(marketplace)],
    [codebuddyPluginMarketplacePath, jsonBody(marketplace)],
  ];
  const plannedMirrors = [];

  for (const skill of sourceSkills) {
    const manifestBody = jsonBody(buildPluginManifest(skill));
    const pluginRoot = path.posix.join("plugins", skill.source);

    // 三份 manifest 覆盖 Claude、CodeBuddy 兼容入口和人工查看入口，保持内容一致。
    plannedWrites.push([path.posix.join(pluginRoot, ".claude-plugin/plugin.json"), manifestBody]);
    plannedWrites.push([path.posix.join(pluginRoot, ".codebuddy-plugin/plugin.json"), manifestBody]);
    plannedWrites.push([path.posix.join(pluginRoot, "plugin.json"), manifestBody]);
    plannedMirrors.push([
      repoPath("skills", skill.source),
      repoPath("plugins", skill.source, "skills", skill.source),
      `plugins/${skill.source}/skills/${skill.source}`,
    ]);
  }

  const changedFiles = plannedWrites
    .filter(([relativePath, body]) => fileBodyDiffers(repoPath(relativePath), body))
    .map(([relativePath]) => relativePath);
  const changedMirrors = plannedMirrors
    .filter(([sourceDir, targetDir]) => !directoriesMatch(sourceDir, targetDir))
    .map(([, , relativePath]) => relativePath);

  if (checkOnly) {
    for (const relativePath of changedFiles.slice(0, 40)) {
      console.error(`out of date file: ${relativePath}`);
    }
    for (const relativePath of changedMirrors.slice(0, 40)) {
      console.error(`out of date skill copy: ${relativePath}`);
    }
    const hiddenCount = Math.max(0, changedFiles.length + changedMirrors.length - 80);
    if (hiddenCount > 0) {
      console.error(`... ${hiddenCount} more out-of-date item(s)`);
    }

    if (changedFiles.length > 0 || changedMirrors.length > 0) {
      process.exitCode = 1;
      return;
    }

    console.log(`checked ${sourceSkills.length} Claude plugin wrapper(s)`);
    return;
  }

  for (const [sourceDir, targetDir] of plannedMirrors) {
    mirrorSkillDirectory(sourceDir, targetDir);
  }

  for (const [relativePath, body] of plannedWrites) {
    const fullPath = repoPath(relativePath);
    ensureDirectory(fullPath);
    if (fileBodyDiffers(fullPath, body)) {
      fs.writeFileSync(fullPath, body, "utf8");
    }
  }

  console.log(`generated ${sourceSkills.length} Claude plugin wrapper(s)`);
  console.log(`wrote ${plannedWrites.length} manifest file(s) and mirrored ${plannedMirrors.length} skill directory/directories`);
}

main();
