---
name: sql-optimization
pack: universal
description: 审查与编写数据库查询时避免性能陷阱——确保命中索引、消除 N+1、禁止全表扫描与 SELECT *、强制分页、控制事务范围。涉及 SQL/ORM 的改动必走。
when_to_use: implementer 写涉及数据库查询/ORM 的代码时；review 阶段 PR 触及 SQL、Repository、DAO、迁移脚本时。
when_NOT_to_use: 纯前端、纯文档、与持久层无关的改动。
---

# Skill: SQL / 查询优化

数据库是大多数后端性能与故障的根源。改动任何查询前后，逐条核对下面规则。

## 必查规则
1. **命中索引**：WHERE/JOIN/ORDER BY 涉及的列必须有索引；新查询若无可用索引，要么加索引迁移，要么说明为何不需。
2. **消除 N+1**：循环里查库 = N+1。用 JOIN / IN 批量 / ORM 的 eager load（如 `select_related`/`Include`/`Preload`）一次取回。
3. **禁止全表扫描**：无 WHERE 或 WHERE 不走索引的大表查询，BLOCK。用 EXPLAIN 验证执行计划。
4. **禁止 `SELECT *`**：只取需要的列，减少 IO 与序列化开销。
5. **强制分页**：列表查询必须有 LIMIT/OFFSET 或游标分页；禁止一次取回无界结果集。
6. **事务范围最小**：事务内不做网络调用/外部 IO；长事务持锁会拖垮并发。
7. **参数化**：永不字符串拼接 SQL（注入风险，见 secure-coding）。

## 正例 / 反例
- ❌ `for id in ids: db.query("... WHERE x=?", id)` → ✅ `db.query("... WHERE x IN (?)", ids)`
- ❌ `SELECT * FROM orders` → ✅ `SELECT id, status FROM orders WHERE user_id=? LIMIT 50`

## 反模式
- ❌ 用 ORM 默认懒加载遍历关联对象（隐形 N+1）
- ❌ 在事务里 `await httpClient.call()`
- ❌ 加索引却忘了写迁移脚本
