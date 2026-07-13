# AGENTS.md — monorepo 根上下文(agent 的常驻地图,v2.6)

> v2 升级:把项目知识从单文件拆成 `.agents/skills/` 体系;Codex custom agent 角色化;新增 `state/` 外置记忆。
> **v2.1 升级**:模型无关——支持 Anthropic / OpenAI / DeepSeek / Qwen / Kimi / GLM 等任意厂商。
> 切厂商只需 2 个 env:`LLM_PROVIDER` + `LLM_API_KEY`。详见 `docs/多模型适配.md`。
> **v2.4 升级**:agent 写码行为纪律(Karpathy adapted)——任何 agent 动手前**必读** `.agents/skills/agent-coding-discipline/SKILL.md`。
> **v2.6 升级**:主 session 收到需求后先判断能否并行分解;可分则走 `task-decomposer` + `parallel-orchestrator`。
> 任何 agent 进入项目后,**先读本文件,再读 agent-coding-discipline,再按需 Read 相关任务 skill**。

---

## 强制行为纪律(动手前必读)

**任何写码 agent**(implementer / explorer / verifier-quality 等)**动手前**,必须先读:
- [`.agents/skills/agent-coding-discipline/SKILL.md`](.agents/skills/agent-coding-discipline/SKILL.md) — 10 条规则 + 4 个失败模式 + 9 项 pre-submit 自检

## 并行优先原则(v2.6,主 session 必读)

**主 session 收到任何"加 X / 改 Y / 实现 Z"的需求,第一件事不是写码,而是判断"能不能并行分解"。**

- 先读 [`.agents/skills/task-decomposer/SKILL.md`](.agents/skills/task-decomposer/SKILL.md),保守判断是否可并行并产出 DAG。
- 可并行 → 读 [`.agents/skills/parallel-orchestrator/SKILL.md`](.agents/skills/parallel-orchestrator/SKILL.md),用 Codex 可用的并行子 agent / 多 worktree 方式 fan-out → fan-in。
- 串行 → 直接走 architect-task-writer + implementer。

默认保守:有疑虑就串行。对真正可分的任务(独立 provider / 独立服务 / 无重叠目录模块),一定要并行,不要把本可同时推进的工作排成队。

**持续推进原则**:小步实现、测试先行、每步可验证,不等于每步都停下来等人。没有遇到必须人工决断的问题前,开发应持续推进到可验证停止条件成立。并行开发时,某个子 session 需要人工决断,只暂停这个子 session 并报告 blocker;其他无 blocker 的子 session 继续原样开发、测试、返回结果。

简版:

1. **读再写** —— 读完整文件,不要扫
2. **想再做** —— 先说假设和 tradeoff
3. **简单** —— 写眼前问题的最少代码
4. **外科手术式** —— diff 像任务一样小;**不顺手 reformat**
5. **fail-first 测试** —— 修 bug 先写失败的测试再修
6. **goal-driven** —— 成功标准先于代码
7. **debug 不靠猜** —— 读完整 stack、复现、一次只改一处
8. **依赖永久** —— 标准库优先,加新依赖必说理由
9. **沟通** —— 说做了什么、为什么、有什么顾虑;不确定的事**精确**说出来
10. **持续推进** —— 无人工决断 blocker 时不要中断;局部 blocked 不拖停其它子 session

4 个失败模式(发现 = 停):Kitchen Sink / Wrong Abstraction / Optimistic Path / Runaway Refactor。

PR 描述自动带 pre-submit checklist(见 `.github/pull_request_template.md`)。

> 这是 harness 的核心文件之一。放在 monorepo 根目录。任何 agent(评审、实现、triage)
> 都会先读它。**目标:一个全新 agent 只读本文件 + 仓库,就能独立完成一个跨服务改动
> 并让集成测试通过。** 把方括号占位换成你项目的真实内容,并随架构演进持续更新。

---

## Session 开始必读

每次进入项目后,按顺序执行:
1. **读本文件** — 确认当前技术栈和命令
2. **读 `.agents/skills/agent-coding-discipline/SKILL.md`** — 写码行为纪律
3. **按需读 skill** — 根据任务类型,参考下方"规范 skill 强制加载"表
4. **BIOS 任务绑定(可选,新对话/新任务开场时问一次)**——主动问用户一句:"这次任务关联哪个 BIOS 工单号?(没有可跳过)"。
   - 用户给了工单号(如 `TES-42`)→ 调用 BIOS MCP 工具 `bios_bind_session`(`issue_key`=用户给的工单号,`session_id`=当前会话 id),把本会话绑定到该工单。绑定后本会话的对话与进度会自动挂到该工单,不用再手动汇报。
   - 用户没给 / 跳过 → 直接开始,不阻塞开发。
   - 可用工具列表里没有 `bios_bind_session`(daemon 未运行,或项目未接入 BIOS)→ 同样跳过,不要报错卡住。

---

## 这个仓库是什么
[一句话:产品是什么、这个 monorepo 包含哪些部分。]

## 目录结构(职责地图)
```
apps/        # 可部署的前端/应用    [web: Next.js;mobile: ...]
services/    # 后端服务            [billing: Go;api: Node;ml: Python]
packages/    # 共享库              [contracts: 跨服务类型/契约;ui;config]
ops/         # 部署/运维脚本        [deploy.sh、rollback.sh、build_and_push.sh ...]
scripts/     # 自动化脚本          [health_report、triage_engine、verify_triage ...]
.github/     # CI/CD 与 AI 评审工作流
```
> 跨服务的接口/类型必须放在 `packages/contracts`,不要在各服务里各自复制。

## 本地开发(agent 必须能复现这些命令)
- 安装依赖:`[make bootstrap / pnpm install && go mod download && pip install -r ...]`
- **一条命令起全栈**:`make dev`(底层:`docker compose -f docker-compose.dev.yml up`)
- **一条命令跑集成测试**:`make test-integration`
- 单测:`make test-unit`;E2E:`make test-e2e`
- 类型检查/lint:`make check`
- **docs-only 例外**:如果 PR 只改文档/说明/markdown/handbook,不需要跑完整 CI 验证;CI 会通过 docs-only path 直接让 `ci-gate` 绿,避免浪费 runner。

## 编码规范
- 语言版本:[Node 20 / Go 1.22 / Python 3.12]
- 格式化:[prettier / gofmt / ruff format] — 提交前必跑,CI 会校验。
- 错误处理:[约定,例如:服务边界返回结构化错误,日志用结构化字段不打印 PII]
- 日志:**所有服务输出结构化日志**(JSON),字段含 `service`、`request_id`、`level`。
  自愈环依赖这些字段做聚类——不结构化,triage 引擎就看不懂。
- 测试:新代码必须带测试;关键路径必须有集成测试。

## 分支 / commit 命名(GitHub 事件自动归因的锚点)
```
monorepo(带服务路由): <type>/<service>/<ISSUE-KEY>-<short-desc>   例: feat/api/TES-42-add-jwt-refresh
单体(无服务路由):     <type>/<ISSUE-KEY>-<short-desc>              例: feat/TES-42-add-jwt-refresh
commit:               <type>(<service>): <短描述>  或  <type>: <短描述>
```
- `type`: `feat` | `fix` | `refactor` | `docs` | `chore` | `test`;`short-desc` 小写连字符 ≤40 字符。
- `ISSUE-KEY`: BIOS 工单号(如 `TES-42`)。接入 BIOS 的项目,建分支 / push / 开 PR 会自动推进对应工单阶段(规划→执行→验证→收尾);**service 段位置不能挪**,BIOS 服务路由(auto-assign、CI-bug 自动建单)取分支第 2 段。未接入 BIOS 可省略工单号段。
- 分支带不了工单号时,在 commit 末尾加 trailer `BIOS-ISSUE: <KEY>` 兜底归因。

## 安全禁区(BLOCK 级,评审会拦)
- 不得硬编码密钥/token;用环境变量 + secrets。
- 新端点默认必须鉴权;越权(IDOR)零容忍。
- 用户输入到 SQL/shell/模板一律参数化/转义。
- 不得在日志/响应中泄露 PII 或凭证。

## 特性开关(强制)
- **每个新功能必须藏在特性开关后**(见 `flags/feature-flags.ts`)。
- 新增 flag 时:在代码里用类型安全的 key,并在 PR 描述里写明 flag 名与灰度计划。
- 不要删旧 flag 而不清理其分支逻辑。

## 部署与回滚(agent 应知道,但不要自己触发 prod)
- 合并到 `main` 后由六阶段流水线自动部署(见 `.github/workflows/deploy.yml`)。
- prod 启用熔断回滚:指标恶化自动回退。agent 不应手动操作 prod。

## 合并与发布纪律(每次合并进 main 都要,强制)
**任何 PR 合并进 `main` 后,必须留下这两类审计锚点,缺一不算完成:**
1. **打 tag** —— 给这次合并打一个 git tag 并 push 到远端。命名按项目既有约定(语义化版本 `vX.Y.Z`,或日期 `vYYYY.MM.DD-N`)。tag 是回滚锚点。
2. **写 Release** —— 在 GitHub 基于该 tag 建一个 Release,正文写清这次合并改了什么、为什么、影响面。Release 是人能读的合并审计。

本 harness 自带 `.github/workflows/release-on-merge.yml`:合并进 `main` 后自动 tag + GitHub Release。项目若不用自动发布,必须在 PR checklist 或 merge 流程里保留等价手动步骤。

手动命令示例:
```bash
gh release create <tag> --target main \
  --title "<tag> — <一句话说明>" \
  --notes "$(printf '改动:...\n原因:...\n影响面:...')"
```

铁律:**没打 tag、没写 Release 的合并 = 没合并完。** 不要直推 main 跳过 PR,也不要合了 PR 就走人。

## 给实现 agent 的工作约定
1. **先出计划与风险,再写码。** 列出你识别到的失败模式、安全边界、可能的技术债。
2. 不扩大范围;任务模板(`prompts/architect-task.md`)第 3 节之外的需求,先问架构师。
3. 自带测试,确保 `make test-integration` 通过;纯文档变更按 docs-only 例外处理,不要为了文档跑重 CI。
4. 开 PR 时在描述里列出权衡点,并指出需要人类重点看的"战略风险"。
5. 复用 `packages/contracts`,不要在服务间复制类型。
6. **有 BIOS 工单号时,阶段各自出 PR + 阶段末显式报 stage/进度(可选,别攒到最后一次性交)**:需求/方案讨论定稿 → 开一个**计划 PR**(落地方案文档,分支/标题带工单号,如 `docs/plan/<KEY>-slug`,把工单推进到 plan_assign);开发完成 → 开**实现 PR**(`feat/<service>/<KEY>-slug`);测试补齐或修 bug → 开**测试/修复 PR**(`fix/<service>/<KEY>-slug`)。分支名/PR 标题带工单号是 GitHub 事件自动推进工单阶段的锚点(见上方"分支 / commit 命名"节)。
   - **在此基础上,若本会话已绑定该工单(开场用 `bios_bind_session` 拿到了 issue_key)**,每个阶段结束时额外显式调用 `bios_update_stage(issue_key, stage)` 报告 stage(`plan_assign` | `execute` | `verify` | `close` 四阶段):需求/计划阶段定稿、准备开发 → `execute`(计划刚出、还没进开发可先报 `plan_assign`);开发进行中/开完实现 PR → `execute`,进入等待评审 → `verify`;PR 合入 main / 任务完成(如"PR #187 已合入 main")→ `close`,并调 `bios_report_progress(issue_key, note)` 补一句精炼的完成摘要。
   - 这是补 GitHub 事件覆盖不到的阶段(尤其非编码工作,如纯讨论、纯测试)的事实信号,BIOS 侧仲裁里 `source=mcp` 权威,**不代替**上面的 PR 节奏,是额外一步。
   - **前提**:仅当已绑定(拿到了 issue_key)才调;没绑定 / 工具不可用 → 跳过,不阻塞开发,不要报错卡住。
   - **没有工单号但接入了 BIOS → 方案/scope 定稿后主动建一张任务(统一建单:MCP 主 + CLI 兜底)**:`bios_create_issue`(MCP)优先,没接入 bios 工具时用 CLI `deepdog issue create`。**一次填全 brief**(你刚做完需求/计划分析,别留空):title + 摘要 + type + **priority**(`urgent`|`high`|`medium`|`low`|`none`)+ **risk_level**(`low`|`medium`|`high`)+ **acceptance_criteria**(可验收的完成条件)+ **context_refs**(先看的文件/符号/决策)—— MCP 入参,或 CLI `--priority`/`--risk`/`--acceptance-criteria`/`--context-ref`,和 daemon 的 session_auto 一样丰富。**建一张、贯穿更新,不是每阶段各建一张**;daemon 会话分析只是兜底且 defer 到你建的这张单(不重复)。scope 明确了再建。**负责人默认你自己**(服务端已对 agent 建的单自动指派创建者;若未指派就 `deepdog issue assign <KEY> --to <你自己>` 补)。**每阶段 PR 带工单号;开 PR 时用 `bios_link_pull_request(issue_key, url)`(CLI 兜底 `deepdog issue link-pr <KEY> --url`)显式关联到任务** —— webhook 无关、幂等,这才是 PR 挂上任务的保证;GitHub 事件自动关联只在装了 App 时是加成,别单靠它(多个 PR 会去重)。
   - 未接入 BIOS / 工具不可用 / daemon 没跑 → 按原节奏走,不强制拆 PR,由 daemon 兜底。

## 给 triage agent 的工作约定
- 错误来源:可观测后端(CloudWatch / Prometheus 等)+ Sentry。
- 按错误指纹聚类、九维打分(见 `scripts/triage_engine.py` + `.agents/skills/triage-severity-scorer/SKILL.md`)。
- 建单前先去重:用 `state/triage-history.jsonl` 识别首次/稳定/回归;已知 flake 自动降权。
- 建议步骤遵循 `.agents/skills/pr-investigator/SKILL.md`。

---

## v2 新增:Skills / Agents / State / Loops

### Skills(`.agents/skills/<name>/SKILL.md`)
项目知识按域拆分。agent 看到 `description` 与 `when_to_use` 自动加载相关 skill。
新增 skill:在 `.agents/skills/` 下建目录,登记到 `.agents/skills/README.md`。

#### 规范 skill 强制加载(开发与评审的共同底线)

任何 agent 在以下情形**必须先 Read 对应 skill 再动手**(不是"自觉",是硬规则):

**所有项目通用(不随技术栈变化):**

| 情形 | 必须先读 skill |
|------|--------------|
| 涉及 SQL/ORM/DB 迁移 | `sql-optimization` |
| 外部调用/并发/缓存/监控 | `performance-review` |
| 处理用户输入/鉴权/密钥/序列化 | `secure-coding` |
| 改 HTTP/RPC 接口 | `api-doc-output` |
| 改 DB 表结构/字段 | `data-model-output` |
| 任意功能变更完成后(PR 前) | `changelog-output` |
| 任何改动的底线 | `clean-code` + `testing-standards` |
| 新功能 | 额外加 `feature-flag-setup` |

**技术栈相关(按项目实际保留/替换):**

> Go 后端保留以下行。其他技术栈的 logging/error-handling/observability 等 skill **已按 pack 提供**(stack:node/rust/java/python、frontend:common/web/mobile/desktop),安装时按 `--stacks` 选装,完整清单见 `.agents/skills/PACKS.md`。

| 情形 | 必须先读 skill | 适用范围 |
|------|--------------|---------|
| 涉及 Go 日志输出 | `go-logging` | Go 后端 |
| 涉及 Go 错误处理 | `go-error-handling` | Go 后端 |
| 新增服务/外部调用/请求链路 | `go-observability` | Go 后端 |

**领域相关(按项目业务保留/移除):**

> 金融/资产类项目保留;非金融项目可删除这两行。

| 情形 | 必须先读 skill | 适用范围 |
|------|--------------|---------|
| 涉及金额/价格/余额/token 数量 | `financial-numerics` | 金融/资产类项目 |
| 前端展示金额或精度敏感数值 | `financial-numerics`(前端部分) | 金融/资产类项目 |

这些 skill 同时被 PR 的 AI 评审引用(见 `.github/workflows/ai-review.yml`)。开发期漏掉的,评审期会拦。

#### 文档同步义务(PR 前必须完成)

> 采用**每服务文档**约定:`docs/services/<服务名>/` 下每服务一组文档(服务名用可读名,可含空格,如 "Order Entry"、"Ledger")。下表落点与对应 skill 一致:

| 改动类型 | 必须同步更新 | 对应 skill |
|---------|------------|-----------|
| 新增/修改 HTTP/RPC 接口 | `docs/services/<服务名>/api.md` | `api-doc-output` |
| 新增/修改 DB 表/字段/索引 | `docs/services/<服务名>/数据模型.md` | `data-model-output` |
| 任意功能变更(PR 前) | `docs/services/<服务名>/CHANGELOG.md` | `changelog-output` |
| 功能模块行为/设计变更 | 对应 `docs/services/<服务名>/<服务名>.md` | — |
| 契约(proto/事件)变更 | 全局契约文档(如 `docs/事件契约底座.md`) | — |
| 全局功能/架构演进 | 全局设计文档(如 `docs/全局设计文档.md`) | — |

**所有相关文档必须在同一 PR 里更新,不允许单独补提。**

### Custom agents(`.codex/agents/<name>.toml`)
角色化的 Codex agent + 推理分层:`explorer`(low)/`implementer`(medium)/`subtask-implementer`(medium)/
`merger`(medium)/四类 `verifier`(分层)/`triage-scorer`(medium)/`checker`(medium)。
**写代码的 agent 不能是判断 done 的 agent;并行子任务不能再递归 spawn 子 agent**。

### State(`state/`)
agent 的外置记忆:`triage-history.jsonl`、`token-usage.jsonl`、`comprehension-log.jsonl`、
`tasks/<id>.json`、`known-flakes.txt`。**append-only 优先**,入仓可审计。

### Goal Loops(`scripts/goal_loop.py`)
跑到一个可验证的停止条件成立为止。implementer 推一步 → checker(独立 sub-agent)判定 done。
长任务、回归修复、CI 自愈都套这个范式。

### Worktrees(`scripts/spawn_agent_worktree.sh`)
并行 agent 任务必须用 `git worktree` 隔离 fs + 隔离 docker compose project name,
否则集成测试一定撞车。

### Parallel Orchestration(`state/orchestration/`)
`task-decomposer` 把需求拆成多轮 DAG,`parallel-orchestrator` 记录每轮 task/result/report。
所有编排状态保存在 `state/orchestration/<task-id>/`,便于断点续跑和事后审计。

### Token 与 Comprehension 报告
- `scripts/token_report.py`:按 day / loop / role / model 聚合花费,集成进每日健康报告
- `scripts/comprehension_metrics.py`:**反认知投降护栏**——comprehension-coverage、
  pr-read-rate、agent-modification-rate 三项指标低于阈值会触发红线告警

---
*保持本文件最新是架构师的职责。它过时一天,agent 就盲一天。*
