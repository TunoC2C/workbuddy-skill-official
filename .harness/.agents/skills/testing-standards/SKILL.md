---
name: testing-standards
pack: universal
description: 审查与编写测试——覆盖边界与异常路径、测行为而非实现细节、避免脆弱测试、关键路径有集成/契约测试、测试可读。
when_to_use: 新增/修改功能时写测试；review 阶段 quality 趟检查测试质量。
when_NOT_to_use: 纯文档改动。
---

# Skill: 测试标准

## 规则
1. 覆盖正常 + 边界 + 异常路径（空、超大、并发、失败）。
2. 测**行为/契约**，不测私有实现细节（实现变测试不该碎）。
3. 避免脆弱测试：不依赖时间/顺序/外部网络（用 fake/mock）。
4. 关键路径必须有集成测试（见 AGENTS.md 的 make test-integration）。
5. 测试名描述行为：`test_拒绝超额提现`。

## 反模式
- ❌ 只测 happy path
- ❌ 断言内部调用次数而非外部可观察结果
- ❌ 真连第三方 API 的"单测"
