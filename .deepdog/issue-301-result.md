已处理：补上了技能市场的重复 plugin 名称检查，避免同名技能再次进入市场。

变更：
- `scripts/generate-claude-marketplace.mjs` 现在会拒绝 `.codebuddy-skill/marketplace.json` 中重复的 plugin name（source）和 displayName（name）。
- `scripts/validate-claude-marketplace.mjs` 现在会校验源市场、Claude 市场、CodeBuddy 市场里的重复 plugin name/displayName。

当前审查结果：268 个 plugin wrapper 校验通过，未发现仍存在重复 plugin 名称。

验证已通过：
- `node scripts\generate-claude-marketplace.mjs --check`
- `node scripts\validate-claude-marketplace.mjs`
