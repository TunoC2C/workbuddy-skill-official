---
name: task-decomposer
pack: universal
description: 主 session 收到需求后第一件事——判断是否可并行分解。输出 DAG(JSON),节点=子任务,边=强依赖。判定保守:有疑虑就串行。
when_to_use: 用户提出任何"加 X / 改 Y / 实现 Z"的需求时,architect-task-writer 之前先跑这一步。
when_NOT_to_use: 已经是单文件 typo 修复 / 单测试调整 / 单文档改这种明显原子操作;复用现有 skill 的标准化任务时。
---

# Skill: Task Decomposer

> 主 session 是指挥,不是实施。收到任何需求,第一件事是决定"这是 1 个任务还是 N 个可并行任务"。
> 默认规则:有疑虑就串行。并行错的代价远大于串行慢。

## 判定矩阵

| 信号 | 可并行 | 必须串行 |
|---|---|---|
| 触及不同的服务/包 | 是 | - |
| 触及不同的目录且无重叠文件 | 是 | - |
| 每个子任务有独立测试 / 验证标准 | 是 | - |
| 共享 schema / DB 迁移 | - | 是,迁移要先做 |
| 共享契约修改(packages/contracts 等) | - | 是,其他任务要等契约稳定 |
| 触及同一个文件 | - | 是,merge conflict 几乎注定 |
| 后端契约新增 + 前端消费 | - | 是,先后端再前端 |
| 跨服务全链路重构 | - | 是,改动顺序敏感 |

决策树:

```text
有任何"必须串行"信号?
  是 -> 整体串行,或拆成"串行多轮,每轮内部可并行"
  否 -> 是否有 2 个以上独立子任务?
          是 -> 并行 DAG
          否 -> 单任务,不必走 orchestrator
```

## 分多轮

如果需求部分可并行、部分必须串行,分轮:

```text
Round 1: 迁移 schema(单任务)
Round 2: 实现 3 个 OAuth provider(并行 3 个)
Round 3: 加前端 Login 选择器(单任务,依赖 Round 2)
```

每一轮内部尽量塞满可并行的子任务。轮之间串行。

## 输出格式

写到 `state/orchestration/<task-id>/decomposition.json`:

```json
{
  "task_id": "add-oauth-providers",
  "requirement": "加 OAuth 三家:Google / GitHub / Microsoft",
  "rounds": [
    {
      "round": 1,
      "parallel": true,
      "subtasks": [
        {
          "id": "oauth-google",
          "scope": "services/auth/providers/google.ts + 测试",
          "no_touch": ["services/auth/index.ts", "packages/contracts/auth.ts"],
          "verifies": "make test-unit services/auth/providers/google"
        },
        {
          "id": "oauth-github",
          "scope": "services/auth/providers/github.ts + 测试",
          "no_touch": ["services/auth/index.ts", "packages/contracts/auth.ts"],
          "verifies": "make test-unit services/auth/providers/github"
        },
        {
          "id": "oauth-microsoft",
          "scope": "services/auth/providers/microsoft.ts + 测试",
          "no_touch": ["services/auth/index.ts", "packages/contracts/auth.ts"],
          "verifies": "make test-unit services/auth/providers/microsoft"
        }
      ]
    },
    {
      "round": 2,
      "parallel": false,
      "subtasks": [
        {
          "id": "wire-providers-in-index",
          "scope": "services/auth/index.ts 注册 3 个 provider",
          "depends_on_round": 1
        }
      ]
    }
  ],
  "rationale": "3 个 provider 文件独立,可并行写;最后统一注册必须等 3 个文件都存在后串行做。"
}
```

## 关键字段

- `scope`:子任务允许触及的范围。实施 agent 越界 = block。
- `no_touch`:显式禁止修改的文件,防止并行子任务同时改同一个文件。
- `verifies`:子任务完成的客观检查命令。
- `depends_on_round`:本子任务依赖哪一轮完成。

## 给主 session 的固定指令

1. 写完 decomposition.json 后,给用户看 decomposition 表格,让用户确认。
2. 用户认为某子任务该再拆 / 不该并行,改 json 重来。
3. 用户确认后,把 `state/orchestration/<task-id>/decomposition.json` 路径交给 `parallel-orchestrator`。

## 反模式

- 默认并行。应该默认串行,只有清晰边界才并行。
- 把"提示词差不多就能拆"当并行候选。必须是文件级别不重叠。
- 不写 `no_touch`。sub-agent 不知道边界,会越界改共享文件。
- 不写 `verifies`。merger 无法机械判断 done。
- 把跨服务契约改动塞进并行。契约改 = 串行先做。
