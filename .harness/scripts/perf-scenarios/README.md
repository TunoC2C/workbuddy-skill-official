# perf-scenarios/ — 性能门禁的 k6 脚本

> 每个文件 = 一个 scenario。perf-gate.yml 会按 matrix 逐个跑,
> 用 `scripts/perf_check.py` 与 `state/perf-baseline.json` 比对。

## 写一个新 scenario

复制 `example.js` → `<your-scenario>.js`,改:

- `BASE_URL`(你的 staging/dev 服务地址)
- 测试路径与并发参数
- 业务断言(用 `check()`)

scenario 名 = 文件名去 `.js`。比如 `checkout.js` 的基线键是 `checkout`。

## 基线如何工作

- **首次跑**:无基线,自动建立,PASS(不能拦还没存在的事)
- **PR 跑**:只比对、不更新基线
- **main 跑**:比对完成后,用指数平滑(EMA α=0.3)滚动更新基线——
  允许产品自然演进,但防止一次抖动定永
- **触发 BLOCK**:p95 恶化 > 20%(env `PERF_P95_REGRESSION_PCT` 可调)
   或 error rate > 1%(`PERF_ERROR_RATE_MAX`)

## 调阈值(临时让 PR 过)

某次大改动需要临时放宽:
```yaml
# 调用方仓 .github/workflows/perf-gate.yml 的 env
PERF_P95_REGRESSION_PCT: '40'   # 临时放宽到 40%
```
合并后改回 20%——不要长期开宽,会失去门禁意义。
