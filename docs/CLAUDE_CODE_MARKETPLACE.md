# Claude Code 插件市场兼容说明

本仓库保留原始 `.codebuddy-skill/marketplace.json` 和 `skills/` 目录，并额外生成 Claude Code 可读取的插件市场结构。

## 市场入口

- Claude Code 市场文件：`.claude-plugin/marketplace.json`
- CodeBuddy 插件兼容市场文件：`.codebuddy-plugin/marketplace.json`
- 插件目录：`plugins/<skill-source>/`

每个原始 skill 都会生成一个独立插件。例如：

```text
skills/airbnb/
plugins/airbnb/
  .claude-plugin/plugin.json
  .codebuddy-plugin/plugin.json
  plugin.json
  skills/airbnb/
```

## 生成与校验

从仓库根目录执行：

```powershell
node scripts/generate-claude-marketplace.mjs
node scripts/validate-claude-marketplace.mjs
node scripts/generate-claude-marketplace.mjs --check
```

生成逻辑以 `.codebuddy-skill/marketplace.json` 为唯一数据源：

- `plugins[].name` 使用原 `source`，保持英文安装 ID 稳定。
- `plugins[].displayName` 优先使用含中文的原 `name`；原 `name` 不含中文时，从 `description_zh` 提炼中文短名。
- `plugins[].description` 优先使用原 `description_zh`，缺失时回退到 `description`。
- 每个插件 manifest 的 `skills` 指向插件内部的 `./skills/<source>`，避免 Claude Code 安装后依赖插件目录外的相对路径。
- `version` 优先使用 marketplace 版本，缺失时读取 `SKILL.md` frontmatter；两处都缺失时不伪造版本，Claude CLI 会给出 warning。

## 维护边界

修改 skill 内容时优先改 `skills/<source>/` 和 `.codebuddy-skill/marketplace.json`，然后重新运行生成脚本。`plugins/<source>/skills/<source>/` 是生成副本，不建议手工编辑。

本地调试时可在 Claude Code 中添加仓库路径：

```text
/plugin marketplace add D:\Programmer\code\yep\workbuddy-skill-official
/plugin install airbnb@codebuddy-skills-official
```
