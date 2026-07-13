<!-- 这份模板自动出现在每个新 PR 的描述里。规则源:.agents/skills/agent-coding-discipline/SKILL.md -->

## 这个 PR 做了什么(一句话)

<!-- 写给一年后忘了这事的你自己 -->

## 为什么

<!-- 触发这个改动的需求/bug/数据/对话 -->

## 你需要重点看什么(战略风险)

<!-- 1~3 条;reviewer 只看这些,逐行交给 AI 评审 -->
- 
- 

---

## Pre-submit 自检(写码 agent 与人都要勾)

来源:[`.agents/skills/agent-coding-discipline/SKILL.md`](../blob/main/codex/skills/agent-coding-discipline/SKILL.md)

- [ ] 我**读了**改动涉及的文件,**复用了现有模式**(Rule 1 — Read before you write)
- [ ] 我**先说了假设和计划**,而不是直接动手(Rule 2 — Think before you code)
- [ ] 这是**眼前问题的最小改动**,没有过度抽象(Rule 3 — Simplicity)
- [ ] **每行 diff 都能被任务解释**,无顺手编辑、无 reformat(Rule 4 — Surgical changes)
- [ ] 改动有**测试覆盖**;bug fix **先写了失败测试**(Rule 5 — Verification)
- [ ] 新功能**藏在特性开关后**,kill switch 名:`FLAGS.________`
- [ ] 每个**新依赖都有理由**,标准库不够才加(Rule 8 — Dependencies)
- [ ] 我**说明了做了什么、为什么、有什么顾虑**(Rule 9 — Communication)
- [ ] 没有人工决断 blocker 时,我**持续推进到可验证停止条件**,没有习惯性中断(Rule 10 — Continuous execution)
- [ ] 如果这是 docs-only PR,我确认只改文档/说明/markdown/handbook,不要求跑重 CI
- [ ] 合并后会留下 tag + GitHub Release(自动 release workflow 或等价手动步骤)

## 4 个失败模式自查(发现 = 停下来,不要硬上)

- [ ] **Kitchen Sink** — "顺便"重构了无关代码?→ revert 那些行
- [ ] **Wrong Abstraction** — 抽象了只被调用一次的东西?→ inline 回去
- [ ] **Optimistic Path** — 只覆盖了 happy path?→ 补错误处理 + 测试
- [ ] **Runaway Refactor** — 一个 fix 改了 > 5 个文件?→ 拆 PR

---

## 信息(选填,有则填)

- 关联 issue / Linear ticket: 
- 灰度计划:`teamOnly → X% → 全量 / kill`
- 部署后**5 分钟内**值得盯的指标:
- 是否涉及 schema 迁移?(向后兼容?rollback 方案?)
