# 技能包分类(PACKS)—— 单一信源

> 每个 SKILL.md 的 frontmatter 必须声明**恰好一个** `pack:` 字段。install.sh 据此按技术栈/业务域选装,
> 避免把语言/业务特定的 skill 焊死进项目无关的仓库。加新 skill 或新包时,**必须在本表登记**。

## 目录结构

源 skills 按 pack 分类到子目录,便于浏览;install.sh 安装时会**拍平**到目标仓的 `.claude/skills/<name>/`(Claude Code/Codex 按扁平一层发现 skill):

```
skills/
  universal/<skill>/
  stack/{go,node,rust,java,python}/<skill>/
  frontend/{common,web,mobile,desktop}/<skill>/
  domain/{finance,web3-solidity}/<skill>/
```

新增 skill:放到对应 `<category>/<subpack>/<name>/SKILL.md`,frontmatter 的 `pack:` 要与目录一致,并在下方成员表登记。

## pack 合法值与安装条件

| pack 值 | 含义 | 安装条件 |
|---|---|---|
| `universal` | 与栈/域无关的通用工程纪律 | **总是安装** |
| `stack:go` | Go 后端 | `--stacks` 命中 或 探测到 `go.mod` |
| `stack:node` | Node 后端 | `--stacks` 命中 或 探测到后端 Node |
| `stack:java` | Java 后端 | `--stacks` 命中 或 探测到 `pom.xml`/`build.gradle` |
| `stack:rust` | Rust | `--stacks` 命中 或 探测到 `Cargo.toml` |
| `stack:python` | Python 后端 | `--stacks` 命中 或 探测到 `pyproject.toml`/`requirements*.txt` |
| `frontend:common` | 任意前端通用 | `--stacks frontend` 或 探测到任一前端平台 |
| `frontend:web` | 前端 · Web 端 | web 平台被选中/探测到 |
| `frontend:mobile` | 前端 · 移动端 | mobile 平台被选中/探测到 |
| `frontend:desktop` | 前端 · 桌面端 | desktop 平台被选中/探测到 |
| `domain:finance` | 金融/资产数值 | 仅 `--domains finance` 显式启用(不自动探测) |
| `domain:web3-solidity` | 智能合约 | `--domains` 命中 或 探测到 `foundry.toml`/`hardhat.config.*`/`*.sol` |

## 探测标志物(install.sh 默认行为,无 `--stacks/--domains` 时)

| 栈/域/平台 | 标志物 |
|---|---|
| stack:go | `go.mod` |
| stack:node(后端) | `package.json` 依赖含 express/koa/nest/fastify/hapi |
| stack:java | `pom.xml` 或 `build.gradle`(`.kts`) |
| stack:rust | `Cargo.toml` |
| stack:python | `pyproject.toml` 或 `requirements*.txt` |
| frontend:web | `package.json` 依赖含 next/nuxt/react-dom/vue/svelte/@angular/core/vite |
| frontend:mobile | 依赖含 react-native/expo/@ionic 或 存在 `pubspec.yaml`(Flutter) |
| frontend:desktop | 依赖含 electron/@tauri-apps |
| domain:web3-solidity | `foundry.toml` 或 `hardhat.config.*` 或 存在 `*.sol` |
| domain:finance | 不自动探测(业务判断),仅 `--domains finance` |

## 当前各包成员

- **universal**(20):agent-coding-discipline、api-doc-output、api-endpoint-creator、architect-task-writer、changelog-output、clean-code、commenting、data-model-output、design-patterns、feature-flag-setup、naming-convention、parallel-orchestrator、performance-review、pr-investigator、secure-coding、sql-optimization、task-decomposer、testing-standards、triage-severity-scorer、weekly-comprehension-check
- **stack:go**(3):go-error-handling、go-logging、go-observability
- **stack:node**(5):node-async-discipline、node-error-handling、node-logging、node-middleware、node-observability
- **stack:rust**(4):rust-concurrency、rust-error-handling、rust-logging、rust-ownership-discipline
- **stack:java**(4):java-error-handling、java-logging、java-observability、java-spring-patterns
- **stack:python**(4):python-error-handling、python-logging、python-observability、python-typing
- **frontend:common**(7):fe-accessibility、fe-component-structure、fe-error-boundary、fe-form-validation、fe-i18n、fe-perf-budget、fe-state-management
- **frontend:web**(4):web-core-vitals、web-hydration、web-rendering-strategy、web-seo
- **frontend:mobile**(5):mobile-list-perf、mobile-native-permissions、mobile-navigation、mobile-offline-state、mobile-platform-parity
- **frontend:desktop**(4):desktop-auto-update、desktop-ipc-security、desktop-native-integration、desktop-packaging
- **domain:finance**(1):financial-numerics
- **domain:web3-solidity**(5):sol-arithmetic-safety、sol-gas-optimization、sol-security、sol-testing、sol-upgradeability

## 安装示例

```bash
bash install.sh <target>                          # 自动探测栈/域
bash install.sh <target> --stacks go              # 只装 universal + Go
bash install.sh <target> --stacks frontend --frontend-platforms web,mobile
bash install.sh <target> --stacks node,java       # 前后端一体(Node+Java)
bash install.sh <target> --domains finance,web3-solidity
bash install.sh <target> --list-packs             # 只列出每个 skill 的 pack,不安装
```
