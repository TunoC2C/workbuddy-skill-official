# 架构师任务模板 — 把一个功能写成结构化 prompt

> 这是新功能路径的第 1 步。架构师不写实现,而是把任务定义为一份**结构化 prompt**,
> agent 据此分解任务、规划、写代码、生成自己的测试。
> prompt 的质量 = 产出的质量。把这份模板复制一份填好,贴给实现 agent。

---

## 1. 目标(Goal)
<!-- 一段话:我们要让用户/系统能做到什么?为什么现在做?成功后世界有何不同? -->

## 2. 背景与上下文(Context)
- 涉及的服务/包:<!-- 例:apps/web、services/billing、packages/contracts -->
- 相关现有代码(给 agent 起点):<!-- 文件路径、关键函数、相关 PR/issue 链接 -->
- 相关业务规则/约束:<!-- 领域规则、合规、性能预算 -->
- 参考:根 `AGENTS.md`(目录结构、本地起栈/跑测试命令、编码规范、禁区)

## 3. 范围(In Scope / Out of Scope)
- ✅ 本次要做:
- ❌ 本次明确不做(防止 agent 过度发挥):

## 4. 验收标准(Acceptance Criteria — 必须可测)
用可验证的条目写,agent 会据此生成测试:
- [ ] <!-- 给定…当…则… -->
- [ ] <!-- 边界/错误路径 -->
- [ ] <!-- 性能/安全要求,如 p95 < 200ms、新端点必须鉴权 -->

## 5. 约束(Constraints)
- 架构边界:<!-- 不得跨过哪些边界、必须复用哪些共享包/契约 -->
- 安全:<!-- 认证/授权要求、不可记录的敏感字段 -->
- 数据/迁移:<!-- 是否涉及 schema 变更?向后兼容要求? -->
- 特性开关:**本功能必须藏在特性开关后**(见 flags/feature-flags.ts),给出 flag 名。

## 6. 测试要求(Testing)
- agent 必须自带:单测 + 集成测试;若涉及 UI,补 E2E。
- 必须能用 `make test-integration` 在本地复现通过。

## 7. 交付与回滚(Delivery)
- 灰度计划:先团队 → X% → 全量(或 kill)。
- 回滚:kill switch flag 名 = <!-- ... -->;熔断回滚由部署流水线保证。

## 8. BIOS 工单与阶段 PR(可选,接入 BIOS 的项目可用)
- 本任务关联的 BIOS 工单号:<!-- 如 TES-42;会话开场若用户给了任务 id,应已用 bios_bind_session 绑定;没有工单号就留空,不影响交付 -->
- 有工单号时,分阶段各自出 PR,别攒到最后一次性交:这份方案定稿 → **计划 PR**(落地本文档,推进工单到 plan_assign);实现完成 → **实现 PR**;补测试/修 bug → **测试/修复 PR**。分支名/PR 标题带工单号(`<type>/<service>/<KEY>-<slug>`)是 GitHub 事件自动推进工单阶段的锚点。
- **每个阶段结束时,若本会话已绑定该工单(有 issue_key),额外显式调用 `bios_update_stage(issue_key, stage)` 报告 stage**(`plan_assign` | `execute` | `verify` | `close` 四阶段):方案定稿/开计划 PR → `plan_assign`(若紧接着就进入开发可直接报 `execute`);开发中/开实现 PR → `execute`;测试补齐待评审 → `verify`;PR 合入 main / 任务完成 → `close`,并调 `bios_report_progress(issue_key, note)` 补一句精炼的完成摘要(如"PR #187 已合入 main")。这是补 GitHub 事件覆盖不到的阶段(尤其非编码工作)的事实信号,不代替上面的 PR 节奏。未绑定 / 工具不可用 → 跳过,不阻塞交付。
- **没有工单号 → 方案/scope 定稿后主动建一张任务(统一建单:MCP 主 + CLI 兜底)**:`bios_create_issue`(MCP)优先;bios 工具没接入时用 CLI `deepdog issue create --title … --type …`。**一次填全 brief**(你刚做完需求/计划分析,别留空):title + 摘要 + type + **priority**(`urgent`|`high`|`medium`|`low`|`none`)+ **risk_level**(`low`|`medium`|`high`)+ **acceptance_criteria**(可验收的完成条件)+ **context_refs**(先看的文件/符号/决策)—— MCP 入参,或 CLI `--priority`/`--risk`/`--acceptance-criteria`/`--context-ref` —— 和 daemon 的 session_auto 一样丰富。**建一张、贯穿 `bios_update_stage` 更新到 close,不是每阶段各建一张**;这是 harness 的活,daemon 会话分析只是兜底且会 defer 到你建的这张单(不重复)。**负责人默认你自己**(服务端已对 agent 建的单自动指派创建者;若发现未指派,`deepdog issue assign <KEY> --to <你自己>` 补,`deepdog auth status` 查自己)。**每阶段各出 PR、分支/标题带工单号;开每个 PR 时用 `bios_link_pull_request(issue_key, url)` 显式关联到任务(CLI 兜底 `deepdog issue link-pr <KEY> --url <url>`)** —— webhook 无关、幂等,这才是 PR 挂上任务的保证;GitHub App 自动关联只在装了 App 时是加成,**别单靠它**(多个 PR 会去重)。每个 PR 推进阶段。两条通道都不可用 → 跳过,由 daemon 兜底。

---

### 给 agent 的固定指令(原样保留)
> 请基于以上内容:①先输出实现计划与你识别到的风险/失败模式,等我确认;
> ②实现代码并生成对应测试;③确保 `make test-integration` 通过;
> ④把功能包在指定的特性开关后;⑤开 PR,PR 描述里列出你做了哪些权衡、
> 哪些地方需要人类评审者重点看战略风险。**不要扩大范围;遇到第 3 节之外的需求先问我。**
> ⑥若第 8 节填了工单号,分阶段各自开 PR(计划/实现/测试),分支名带工单号,让 GitHub 事件自动推进阶段;若会话已绑定该工单,阶段末还需显式调 `bios_update_stage`/`bios_report_progress` 报 stage 与进度。
