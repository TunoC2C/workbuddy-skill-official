# state/orchestration/ — 并行任务编排的外置状态(v2.6)

> 任何由 `task-decomposer` + `parallel-orchestrator` 跑过的任务,留下完整可审计的轨迹。
> 主 session 崩溃可断点续;事后可回看每一轮 fan-out/fan-in 决策。
> 也是 comprehension-metrics 的数据源(架构师每周自检"哪些任务被并行了、整合是否顺利")。

## 目录约定

```text
state/orchestration/
└── <task-id>/                          # 一个用户需求一个目录
    ├── decomposition.json               # task-decomposer 产出的 DAG
    ├── round-1/
    │   ├── <sub-id>.task.md             # 主 session 写,派发给 sub-agent 的 prompt
    │   ├── <sub-id>.result.md           # sub-agent 返回后由主 session 写入
    │   └── round-report.md              # merger 整合后写
    ├── round-2/
    │   └── ...
    └── final-state.json                 # 全任务完成后由主 session 写
```

## 命名规则

- `<task-id>`:kebab-case,简短描述,如 `add-oauth-providers`、`refactor-billing-v2`
- `<sub-id>`:同样 kebab-case,在父任务内唯一,如 `oauth-google`、`oauth-github`
- 轮数:从 `round-1` 开始连续编号

## 写入规则

- append-only 精神:轮一旦开始写,不要回头改前面轮的文件
- 中断重跑需要新轮:`round-N+1` 接着写,而非覆盖 `round-N`
- 大对象(完整 diff、长输出)只存指针,不存 blob。真 diff 在 git history 里

## 例子:OAuth 三家任务

```text
state/orchestration/add-oauth-providers/
├── decomposition.json
├── round-1/                                # 3 个 provider 并行
│   ├── oauth-google.task.md
│   ├── oauth-google.result.md
│   ├── oauth-github.task.md
│   ├── oauth-github.result.md
│   ├── oauth-microsoft.task.md
│   ├── oauth-microsoft.result.md
│   └── round-report.md                     # merger 写:3 个分支 merge 成功,集成测试绿
├── round-2/                                # 单任务串行
│   ├── wire-providers-in-index.task.md
│   ├── wire-providers-in-index.result.md
│   └── round-report.md
└── final-state.json                        # status=success, 总耗时 42min
```

## 不要做

- 不要把这个目录 .gitignore 掉。它是审计/comprehension 的基础。
- 不要把 result.md 放敏感数据。sub-agent 返回应该是结构化摘要,不是原始日志。
- 不要删旧任务目录。需要轮转时用单独脚本或归档策略。
