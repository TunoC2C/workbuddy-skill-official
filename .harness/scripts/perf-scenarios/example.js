// example.js — 复制并改名为 <你的 scenario 名>.js
//
// 跑法(本地):k6 run --summary-export=summary.json example.js
// 在 CI 里 perf-gate.yml 会自动用 --summary-export 跑并把 summary 喂给 perf_check.py
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';

export const options = {
  // 阶梯式加压:30 秒升到 50 个 VU,稳定 1 分钟,然后降回
  stages: [
    { duration: '30s', target: 50 },
    { duration: '1m',  target: 50 },
    { duration: '15s', target: 0 },
  ],
  thresholds: {
    // 这些是给 k6 自己看的 hard limit;perf_check.py 还会再做相对比较
    http_req_duration: ['p(95)<800'],   // p95 <800ms 总是合格
    http_req_failed:   ['rate<0.02'],   // 错误率 <2% 总是合格
  },
};

export default function () {
  const res = http.get(`${BASE_URL}/health`);
  check(res, {
    'status is 200': (r) => r.status === 200,
    'body has ok':   (r) => r.body && r.body.includes('ok'),
  });
  sleep(0.1);
}
