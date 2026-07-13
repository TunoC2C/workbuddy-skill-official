"""适配器层 — 把"厂商相关"的代码隔离在这里。

换工具(可观测后端 / 工单系统 / 通知渠道 / 模型)只改本文件,
health_report / triage_engine / verify_triage 三个主流程都不动。

所有适配器都提供一个 `mock` 实现,这样在没有任何真实凭证时也能本地跑通整条
自愈环,验证逻辑(CI 里设 OBSERVABILITY_BACKEND=mock、TRACKER=github-dryrun 即可)。

v2 新增:
  - record_token_usage:把每次模型调用 append 进 state/token-usage.jsonl
  - append_triage_history / load_known_fingerprints:用 state 文件做指纹去重与回归识别
  - load_known_flakes:读 state/known-flakes.txt 自动降权
  - ModelAdapter.summarize 现在会自动记 tokens(若 SDK 返回 usage 字段)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# state/ 路径解析:从 scripts/ 上一级找 state/(若不存在则在 cwd 下建)
# ---------------------------------------------------------------------------
def _state_dir() -> Path:
    here = Path(__file__).resolve().parent.parent
    sd = here / "state"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "tasks").mkdir(parents=True, exist_ok=True)
    return sd


STATE = _state_dir()


# ---------------------------------------------------------------------------
# Token 记账:每次模型调用 append 一行,供 token_report.py 聚合
# ---------------------------------------------------------------------------
def record_token_usage(*, loop: str, role: str, model: str,
                       input_tokens: int = 0, output_tokens: int = 0,
                       extra: dict | None = None) -> None:
    rec = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "loop": loop,
        "role": role,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    if extra:
        rec.update(extra)
    with (STATE / "token-usage.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 指纹历史:append-only 事件流,支撑"首次/稳定/回归"判定
# ---------------------------------------------------------------------------
def append_triage_history(*, fingerprint: str, action: str, score: float,
                          service: str, extra: dict | None = None) -> None:
    """action ∈ {created, updated, reopened, closed}。"""
    rec = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fingerprint": fingerprint,
        "action": action,
        "score": score,
        "service": service,
    }
    if extra:
        rec.update(extra)
    with (STATE / "triage-history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_known_fingerprints(*, within_days: int = 30) -> dict[str, str]:
    """返回 {fingerprint: last_action} 中最近 within_days 内的事件。"""
    path = STATE / "triage-history.jsonl"
    if not path.exists():
        return {}
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=within_days)
    last: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            ts = dt.datetime.fromisoformat(rec["ts"])
            if ts >= cutoff:
                last[rec["fingerprint"]] = rec.get("action", "")
        except Exception:
            continue
    return last


def load_known_flakes() -> set[str]:
    """读 state/known-flakes.txt,返回应自动降权的指纹集合。"""
    path = STATE / "known-flakes.txt"
    if not path.exists():
        return set()
    out: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            out.add(line)
    return out


# =============================================================================
# 数据模型
# =============================================================================
@dataclass
class ErrorEvent:
    """一条原始错误事件(已规整)。"""
    service: str
    message: str
    level: str = "error"
    endpoint: str | None = None
    user_id: str | None = None
    timestamp: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def fingerprint(self) -> str:
        """用于聚类的稳定指纹:服务 + 去掉可变部分的消息。

        规整策略:把任何"含数字的 token"(如 evt_0000…、uuid、30000ms、user-42)
        整体替换为 <id>,再压缩空白。这样同类错误(只是 id/数值不同)会落到同一簇。
        """
        norm = self.message.lower()
        norm = re.sub(r"\b\w*\d\w*\b", "<id>", norm)   # 任何含数字的 token
        norm = re.sub(r"\s+", " ", norm).strip()
        return hashlib.sha1(f"{self.service}|{norm}".encode()).hexdigest()[:12]


@dataclass
class Cluster:
    fingerprint: str
    service: str
    sample_message: str
    count: int
    affected_users: set[str] = field(default_factory=set)
    affected_endpoints: set[str] = field(default_factory=set)
    samples: list[ErrorEvent] = field(default_factory=list)
    score: float = 0.0
    dimensions: dict[str, float] = field(default_factory=dict)


# =============================================================================
# 可观测后端适配器:CloudWatch / Prometheus / mock
# =============================================================================
class ObservabilityAdapter:
    @staticmethod
    def create() -> "ObservabilityAdapter":
        backend = os.getenv("OBSERVABILITY_BACKEND", "mock").lower()
        if backend == "cloudwatch":
            return _CloudWatchAdapter()
        if backend == "prometheus":
            return _PrometheusAdapter()
        return _MockObservability()

    def fetch_errors(self, lookback_hours: int) -> list[ErrorEvent]:
        raise NotImplementedError


class _CloudWatchAdapter(ObservabilityAdapter):
    def fetch_errors(self, lookback_hours: int) -> list[ErrorEvent]:
        import boto3  # 延迟导入,只有用到才需要

        logs = boto3.client("logs")
        end = dt.datetime.now(dt.timezone.utc)
        start = end - dt.timedelta(hours=lookback_hours)
        # CloudWatch Logs Insights:依赖服务输出结构化 JSON 日志(见 AGENTS.md)
        query = (
            "fields @timestamp, service, level, message, endpoint, user_id "
            "| filter level in ['error','fatal'] | sort @timestamp desc | limit 5000"
        )
        start_resp = logs.start_query(
            logGroupName=os.environ["LOG_GROUP"],
            startTime=int(start.timestamp()),
            endTime=int(end.timestamp()),
            queryString=query,
        )
        qid = start_resp["queryId"]
        import time
        while True:
            res = logs.get_query_results(queryId=qid)
            if res["status"] in ("Complete", "Failed", "Cancelled"):
                break
            time.sleep(1)
        events: list[ErrorEvent] = []
        for row in res.get("results", []):
            d = {c["field"]: c["value"] for c in row}
            events.append(ErrorEvent(
                service=d.get("service", "unknown"),
                message=d.get("message", ""),
                level=d.get("level", "error"),
                endpoint=d.get("endpoint"),
                user_id=d.get("user_id"),
                timestamp=d.get("@timestamp"),
                raw=d,
            ))
        return events


class _PrometheusAdapter(ObservabilityAdapter):
    def fetch_errors(self, lookback_hours: int) -> list[ErrorEvent]:
        # 占位:Prometheus 本身不存日志,通常配 Loki。这里给出形态,接 Loki /query_range。
        import requests
        base = os.environ["LOKI_URL"].rstrip("/")
        end = dt.datetime.now(dt.timezone.utc)
        start = end - dt.timedelta(hours=lookback_hours)
        resp = requests.get(
            f"{base}/loki/api/v1/query_range",
            params={
                "query": '{level=~"error|fatal"} | json',
                "start": int(start.timestamp() * 1e9),
                "end": int(end.timestamp() * 1e9),
                "limit": 5000,
            },
            timeout=30,
        )
        resp.raise_for_status()
        events: list[ErrorEvent] = []
        for stream in resp.json().get("data", {}).get("result", []):
            labels = stream.get("stream", {})
            for _ts, line in stream.get("values", []):
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    d = {"message": line}
                events.append(ErrorEvent(
                    service=d.get("service", labels.get("service", "unknown")),
                    message=d.get("message", line),
                    level=d.get("level", "error"),
                    endpoint=d.get("endpoint"),
                    user_id=d.get("user_id"),
                    raw=d,
                ))
        return events


class _MockObservability(ObservabilityAdapter):
    """无凭证也能跑:返回一组可复现的假错误,用于本地验证整条环路。"""
    def fetch_errors(self, lookback_hours: int) -> list[ErrorEvent]:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        out: list[ErrorEvent] = []

        # 模拟一次 billing 支付 webhook 的事故性爆发(应越过阈值并建单)。
        # 事件 id 用 8+ 位十六进制,会被指纹规整后聚成同一簇。
        for i in range(14):
            out.append(ErrorEvent(
                service="billing",
                message=f"Stripe webhook signature verification failed for event evt_{i:08x}b3d",
                level="fatal" if i % 4 == 0 else "error",
                endpoint="/webhooks/stripe/checkout",
                user_id=f"u_{200 + i}",
                timestamp=now,
            ))

        # 一组中等规模的 NPE(用户读取路径)
        for uid in ("u_42", "u_87", "u_91", "u_42", "u_103"):
            out.append(ErrorEvent(
                service="api",
                message="NullPointerException reading user.profile.avatar",
                endpoint="/v1/users/profile",
                user_id=uid,
                timestamp=now,
            ))

        # 低频噪音(应被阈值过滤,验证去噪)
        out.append(ErrorEvent(
            service="ml",
            message="Inference timeout after 30000ms on model rerank-v3",
            endpoint="/v1/rerank",
            timestamp=now,
        ))
        return out


# =============================================================================
# Sentry 适配器(可选的第二错误源,与可观测后端合并)
# =============================================================================
def fetch_sentry_issues(lookback_hours: int) -> list[ErrorEvent]:
    token = os.getenv("SENTRY_AUTH_TOKEN")
    if not token:
        return []
    import requests
    org = os.environ["SENTRY_ORG"]
    project = os.environ["SENTRY_PROJECT"]
    resp = requests.get(
        f"https://sentry.io/api/0/projects/{org}/{project}/issues/",
        headers={"Authorization": f"Bearer {token}"},
        params={"statsPeriod": f"{lookback_hours}h", "query": "is:unresolved"},
        timeout=30,
    )
    resp.raise_for_status()
    events: list[ErrorEvent] = []
    for issue in resp.json():
        events.append(ErrorEvent(
            service=issue.get("project", {}).get("slug", "sentry"),
            message=issue.get("title", ""),
            level=issue.get("level", "error"),
            endpoint=(issue.get("culprit") or None),
            user_id=None,
            raw={"sentry_id": issue.get("id"), "count": issue.get("count")},
        ))
    return events


# =============================================================================
# 工单系统适配器:Linear / Jira / GitHub Issues / dry-run
# =============================================================================
class TrackerAdapter:
    @staticmethod
    def create() -> "TrackerAdapter":
        tracker = os.getenv("TRACKER", "github-dryrun").lower()
        if tracker == "linear":
            return _LinearTracker()
        # Jira / GitHub 可按相同接口扩展
        return _DryRunTracker()

    def find_open_by_fingerprint(self, fp: str) -> dict | None:
        raise NotImplementedError

    def create_issue(self, title: str, body: str, fp: str, severity: float) -> str:
        raise NotImplementedError

    def update_issue(self, issue_id: str, body: str) -> None:
        raise NotImplementedError

    def reopen_issue(self, issue_id: str) -> None:
        raise NotImplementedError

    def close_issue(self, issue_id: str, comment: str) -> None:
        raise NotImplementedError


class _LinearTracker(TrackerAdapter):
    API = "https://api.linear.app/graphql"

    def _gql(self, query: str, variables: dict) -> dict:
        import requests
        resp = requests.post(
            self.API,
            headers={"Authorization": os.environ["LINEAR_API_KEY"],
                     "Content-Type": "application/json"},
            json={"query": query, "variables": variables},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(data["errors"])
        return data["data"]

    # 约定:把 fingerprint 写进工单标题里的 [fp:xxxx],便于去重检索。
    def find_open_by_fingerprint(self, fp: str) -> dict | None:
        q = """query($q:String!){ issues(filter:{title:{contains:$q}}, first:5){
                 nodes{ id title state{ name type } } } }"""
        nodes = self._gql(q, {"q": f"[fp:{fp}]"})["issues"]["nodes"]
        return nodes[0] if nodes else None

    def create_issue(self, title, body, fp, severity):
        team = os.environ["LINEAR_TEAM_ID"]
        q = """mutation($t:String!,$d:String!,$team:String!){
                 issueCreate(input:{title:$t, description:$d, teamId:$team}){ issue{ id } } }"""
        full_title = f"{title} [fp:{fp}]"
        return self._gql(q, {"t": full_title, "d": body, "team": team})["issueCreate"]["issue"]["id"]

    def update_issue(self, issue_id, body):
        q = """mutation($id:String!,$d:String!){ issueUpdate(id:$id, input:{description:$d}){ success } }"""
        self._gql(q, {"id": issue_id, "d": body})

    def reopen_issue(self, issue_id):
        # 需要把 state 切回 unstarted/started;此处省略 state id 查询,留作接入时填。
        pass

    def close_issue(self, issue_id, comment):
        q = """mutation($id:String!){ issueUpdate(id:$id, input:{stateId:"<DONE_STATE_ID>"}){ success } }"""
        self._gql(q, {"id": issue_id})


class _DryRunTracker(TrackerAdapter):
    """打印将要做的操作而不真正写入。默认值,保证开箱即跑、零副作用。"""
    def find_open_by_fingerprint(self, fp): return None
    def create_issue(self, title, body, fp, severity):
        print(f"[DRY-RUN] CREATE ticket  sev={severity:.1f}  [fp:{fp}]  {title}")
        print(_indent(body)); return f"dry-{fp}"
    def update_issue(self, issue_id, body):
        print(f"[DRY-RUN] UPDATE ticket {issue_id}")
    def reopen_issue(self, issue_id):
        print(f"[DRY-RUN] REOPEN ticket {issue_id} (regression detected)")
    def close_issue(self, issue_id, comment):
        print(f"[DRY-RUN] CLOSE ticket {issue_id}: {comment}")


# =============================================================================
# 通知适配器:Teams / Slack 入站 webhook / stdout
# =============================================================================
def notify(text: str) -> None:
    url = os.getenv("NOTIFY_WEBHOOK_URL")
    if not url:
        print("[NOTIFY:stdout]\n" + text)
        return
    import requests
    # Teams 与 Slack 的 webhook 都接受 {"text": ...} 形态的简单负载
    requests.post(url, json={"text": text}, timeout=15).raise_for_status()


# =============================================================================
# 模型适配器:生成摘要 / 给建议。换厂商只改这里。
# =============================================================================
# ---------------------------------------------------------------------------
# 已知厂商的 OpenAI 兼容端点表(v2.1 多模型适配)
# 切厂商只改 env LLM_PROVIDER + LLM_API_KEY 即可;没列出的厂商用 custom + LLM_BASE_URL
# ---------------------------------------------------------------------------
PROVIDER_PRESETS = {
    # provider:    (base_url,                                         default_model)
    "openai":     ("https://api.openai.com/v1",                        "gpt-4o-mini"),
    "deepseek":   ("https://api.deepseek.com/v1",                      "deepseek-chat"),
    "qwen":       ("https://dashscope.aliyuncs.com/compatible-mode/v1","qwen-plus"),
    "kimi":       ("https://api.moonshot.cn/v1",                       "moonshot-v1-32k"),
    "glm":        ("https://open.bigmodel.cn/api/paas/v4",             "glm-4-plus"),
    "baichuan":   ("https://api.baichuan-ai.com/v1",                   "Baichuan4"),
    "siliconflow":("https://api.siliconflow.cn/v1",                    "deepseek-ai/DeepSeek-V3"),
    # anthropic 走原生 SDK,不在 OpenAI 兼容路径
    "anthropic":  (None,                                               "claude-sonnet-4-6"),
}


class ModelAdapter:
    """模型无关的对外接口。切厂商只改两个 env:LLM_PROVIDER + LLM_API_KEY。

    优先级(从高到低):
      1. 显式传 model + 显式传 provider(若 summarize 调用方指定)
      2. 角色/环节专属覆盖:LLM_MODEL_<UPPER_ROLE>(例:LLM_MODEL_VERIFIER_SECURITY)
      3. 全局默认:LLM_PROVIDER(默认 anthropic 以保持向后兼容)+ LLM_MODEL
      4. 厂商预设的 default_model
    """

    @staticmethod
    def _resolve(model: str | None, role: str) -> tuple[str, str, str]:
        """返回 (provider, model, base_url)。"""
        provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
        if provider not in PROVIDER_PRESETS:
            provider = "openai"   # 未知厂商默认按 OpenAI 兼容协议走
        base_url, default_model = PROVIDER_PRESETS[provider]
        # 自定义 base_url(用于私有部署 / 未在预设里的厂商)
        base_url = os.getenv("LLM_BASE_URL") or base_url
        # 角色级覆盖
        role_env = f"LLM_MODEL_{role.upper().replace('-', '_')}"
        used_model = (
            model
            or os.getenv(role_env)
            or os.getenv("LLM_MODEL")
            or os.getenv("HEALTH_MODEL")          # v1 兼容
            or default_model
        )
        return provider, used_model, base_url or ""

    @staticmethod
    def summarize(prompt: str, model: str | None = None,
                  *, loop: str = "ad-hoc", role: str = "summarizer") -> str:
        # Claude Code OAuth token 优先。设了 CLAUDE_CODE_OAUTH_TOKEN(或 ANTHROPIC_AUTH_TOKEN)
        # 就走 Anthropic Bearer 鉴权,不依赖云厂商 API key。
        oauth = os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or os.getenv("ANTHROPIC_AUTH_TOKEN")
        if oauth:
            role_env = f"LLM_MODEL_{role.upper().replace('-', '_')}"

            # OAuth 路只走 Anthropic:任何来源的模型值只要不是 claude 模型就忽略,
            # 避免遗留 gpt-* 配置打到 Anthropic 后 404。
            def _claude_only(v: str | None) -> str:
                return v if v and "claude" in v.lower() else ""

            used_model = (
                _claude_only(model)
                or _claude_only(os.getenv(role_env))
                or _claude_only(os.getenv("CC_MODEL"))
                or _claude_only(os.getenv("LLM_MODEL"))
                or "claude-sonnet-4-6"
            )
            try:
                return _call_anthropic(prompt, used_model, oauth, loop, role, oauth=True)
            except Exception as e:
                record_token_usage(loop=loop, role=role, model=used_model,
                                   input_tokens=0, output_tokens=0,
                                   extra={"error": str(e)[:200], "provider": "anthropic",
                                          "auth": "oauth"})
                return f"[模型调用失败 provider=anthropic(CC-oauth) model={used_model}:{str(e)[:120]}]"

        provider, used_model, base_url = ModelAdapter._resolve(model, role)
        # v2.1: 优先读通用 LLM_API_KEY;若没设,回退到厂商专属 key(向后兼容)
        key = (
            os.getenv("LLM_API_KEY")
            or os.getenv(f"{provider.upper()}_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")     # 向后兼容
        )
        if not key:
            record_token_usage(loop=loop, role=role, model=used_model,
                               input_tokens=0, output_tokens=0,
                               extra={"stub": True, "provider": provider})
            return "[模型未配置:跳过 AI 摘要,以下为机器统计]"

        try:
            if provider == "anthropic":
                return _call_anthropic(prompt, used_model, key, loop, role)
            return _call_openai_compat(prompt, used_model, key, base_url, provider, loop, role)
        except Exception as e:
            # 模型层故障不能拖垮主流程(fail-safe)
            record_token_usage(loop=loop, role=role, model=used_model,
                               input_tokens=0, output_tokens=0,
                               extra={"error": str(e)[:200], "provider": provider})
            return f"[模型调用失败 provider={provider} model={used_model}:{str(e)[:120]}]"


def _call_anthropic(prompt: str, model: str, key: str, loop: str, role: str,
                    *, oauth: bool = False) -> str:
    from anthropic import Anthropic
    if oauth:
        client = Anthropic(
            auth_token=key,
            default_headers={"anthropic-beta": "oauth-2025-04-20"},
        )
    else:
        client = Anthropic(api_key=key)
    msg = client.messages.create(
        model=model, max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = getattr(msg, "usage", None)
    record_token_usage(
        loop=loop, role=role, model=model,
        input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
        output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
        extra={"provider": "anthropic", "auth": "oauth" if oauth else "api_key"},
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _call_openai_compat(prompt: str, model: str, key: str, base_url: str,
                        provider: str, loop: str, role: str) -> str:
    """所有 OpenAI 兼容协议的厂商共用此路径(OpenAI / DeepSeek / Qwen / Kimi / GLM / ...)."""
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url=base_url or None)
    resp = client.chat.completions.create(
        model=model, max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = getattr(resp, "usage", None)
    record_token_usage(
        loop=loop, role=role, model=model,
        input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
        output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
        extra={"provider": provider},
    )
    return resp.choices[0].message.content or ""


def _indent(s: str, n: int = 4) -> str:
    pad = " " * n
    return "\n".join(pad + line for line in s.splitlines())
