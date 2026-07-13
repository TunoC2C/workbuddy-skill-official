---
name: clean-code
pack: universal
description: 审查与编写代码整洁度——函数职责单一且短小、控制圈复杂度与嵌套、消除重复(DRY)、统一抽象层级、删除死代码与魔法值。
when_to_use: 任何写码/重构；review 阶段 quality 趟。
when_NOT_to_use: 纯配置/文档。
---

# Skill: 代码整洁

## 规则
1. 函数职责单一、短小；超长函数拆分。
2. 控制嵌套深度，早返回替代深 if。
3. DRY：重复逻辑提取；但避免错误抽象（见 design-patterns 的 YAGNI）。
4. 同一函数内保持一致抽象层级。
5. 魔法值提为具名常量；删除死代码。

## 反模式
- ❌ 一个函数做校验+查库+计算+发通知
- ❌ `if (status == 3)` 魔法数字
