---
name: naming-convention
pack: universal
description: 审查与编写标识符命名——名字要表意（揭示意图与领域术语），与团队词汇表一致，避免缩写歧义与误导性命名。格式类规则（大小写）由 linter 管，本 skill 管语义。
when_to_use: 新增/重命名函数、变量、类型、模块、接口字段时；review 阶段 quality 趟。
when_NOT_to_use: 仅格式调整（交给 linter）。
---

# Skill: 命名语义

linter 管大小写格式，本 skill 管"名字是否表意"。

## 规则
1. 名字揭示意图：`elapsedSeconds` 优于 `t`；`isEligible` 优于 `flag`。
2. 用领域术语，与团队词汇表（见 docs）一致：同一概念全仓一个名字。
3. 避免误导：不要把返回 list 的函数命名为 `getUser`。
4. 布尔用 is/has/can 前缀；集合用复数。
5. 避免无意义缩写（`usr`/`tmp2`），除非是公认领域缩写。

## 反模式
- ❌ `data`/`info`/`manager`/`process` 这类空泛名
- ❌ 同一概念在不同模块叫 `userId` 和 `uid`
