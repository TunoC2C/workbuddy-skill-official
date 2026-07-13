# state/ — agent 的外置记忆

> 模型每次都失忆。**记忆必须放在磁盘上,而不是 context 里**(Addy Osmani《long-running agents》)。
> 这个目录就是 harness 的"骨髓":跨运行、跨会话、跨 agent 的持久状态。

## 文件清单

| 文件 | 格式 | 写入者 | 读取者 | 用途 |
|---|---|---|---|---|
| `triage-history.jsonl` | 每行一个事件 | triage_engine.py | triage_engine, pr-investigator skill | 指纹的"前世今生"——首次?稳定?回归? |
| `health-baseline.json` | 单一 JSON | health_report.py | health_report (next run) | 各服务错误率/延迟的滚动基线,用于"今天偏离基线多少" |
| `token-usage.jsonl` | 每行一次调用 | _adapters.record_token_usage / workflows | token_report.py, daily-health | 按 loop / role / model 聚合 token 花费 |
| `known-flakes.txt` | 每行一个指纹 | 人或脚本手动 append | triage_engine | 自动降权"已知不稳定"测试/错误 |
| `comprehension-log.jsonl` | 每行一次自检 | **架构师本人** | comprehension_metrics.py | 反认知投降护栏的数据源 |
| `tasks/<task-id>.json` | 单一 JSON | goal_loop.py | goal_loop (resume), 人 | 长任务的逐轮进度,可断点续 |
| `tasks/<task-id>.md` | Markdown | architect-task-writer skill | implementer, goal_loop | 任务规约(架构师写的) |
| `orchestration/<task-id>/` | JSON/Markdown | task-decomposer / parallel-orchestrator | subtask-implementer, merger | v2.6 并行任务编排轨迹 |

## 写入规则

1. **append-only 优先**:`jsonl` 形态的文件**永远 append,不改不删**(便于审计与时间旅行)。
2. **单一 JSON 文件**(`health-baseline.json`、`tasks/*.json`)**整体重写**,不要 patch——避免并发损坏。
3. **不写 PII / 凭证**——这里是版本化、可能被多人 review 的目录。

## git 化策略(默认:state/ 入仓)

state/ 的内容是 harness 的"行为记忆",**强烈建议提交进仓库**:
- 让回归能跨人识别
- 让 token 账单能被全员可见
- 让架构师的 comprehension log 不可掩盖(这是反认知投降的关键)

只在 `.gitignore` 里排除两类:
```
state/tasks/*.tmp.*          # 任务执行中的临时半成品
state/_local/                # 用户本地实验,不入仓
```

## 大小管理

每月跑一次轮转:
```bash
# 把 triage-history 中超过 90 天的事件归档
python3 scripts/rotate_state.py --older-than 90d --archive state/_archive/
```
(rotate_state.py 是后续可加的小脚本,本仓库未提供——形态够清晰)
