---
name: secure-coding
pack: universal
description: 审查与编写代码时的应用级安全判断——参数化输入、鉴权与授权分离、越权(IDOR)零容忍、密钥不入代码、日志不泄露 PII/凭证、防 SSRF/CSRF/不安全反序列化。
when_to_use: 任何处理用户输入、鉴权授权、外部请求、序列化、日志输出的改动；review 阶段 security 趟。
when_NOT_to_use: 纯样式/文案/与数据流无关的改动。
---

# Skill: 安全编码

钱与信任在这里被摧毁。下面每条都是 BLOCK 级。

## 必查规则
1. **注入**：用户输入到 SQL/shell/模板/表达式一律参数化或转义，禁止拼接。
2. **鉴权 ≠ 授权**：登录(鉴权)和"能否操作这条资源"(授权)分开判。新端点默认必须鉴权。
3. **越权(IDOR)零容忍**：用资源 owner 校验，不能仅凭前端传的 id 就返回数据。
4. **密钥**：绝不硬编码 token/私钥；用环境变量 + secrets 管理。
5. **日志/响应脱敏**：不打印 PII、凭证、完整卡号、私钥、签名原文。
6. **SSRF**：对用户可控的出站 URL 做白名单/网段校验。
7. **反序列化**：不反序列化不可信数据为可执行对象。

## 反模式
- ❌ `f"SELECT ... WHERE name='{name}'"`
- ❌ `if user.is_logged_in: return order`（缺 owner 校验 → IDOR）
- ❌ `logger.info(f"token={token}")`
- ❌ 把密钥写进 .env 并提交入库
