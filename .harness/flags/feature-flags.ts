/**
 * 特性开关封装 — AI-First 流水线的发布安全阀
 * ============================================================================
 * 每个新功能都藏在开关后。发布模式:先对团队开 → 按百分比灰度 → 全量或杀掉。
 * kill switch 即时关闭功能,无需部署。指标恶化几小时内拉掉。A/B 走同一套系统。
 *
 * 厂商可替换:默认接 Statsig,但所有厂商相关代码都隔离在 `FlagProvider` 适配器后。
 * 换 LaunchDarkly / Unleash / Flagsmith / GrowthBook 只需实现一个新 provider,
 * 业务代码调用的 `flags.isEnabled(...)` / `flags.getVariant(...)` 完全不变。
 *
 * 设计要点:
 *  - 类型安全的 flag key(集中登记,杜绝裸字符串散落各处)
 *  - 永远 fail-safe:provider 异常时回退到 flag 的默认值,绝不让开关系统拖垮主流程
 *  - kill switch 与灰度是同一机制的两端(0% = 杀掉,100% = 全量)
 */

// ============================================================================
// 1. 集中登记所有 flag(唯一事实来源)
// ============================================================================
export const FLAGS = {
  // 示例:新结账流程。架构师在任务模板里指定的 flag 名应登记到这里。
  NEW_CHECKOUT_FLOW: 'new_checkout_flow',
  RERANK_V3: 'rerank_v3',
  AVATAR_LAZY_LOAD: 'avatar_lazy_load',
} as const;

export type FlagKey = (typeof FLAGS)[keyof typeof FLAGS];

/** 每个 flag 的默认值(provider 不可用时的 fail-safe 回退,务必保守=关闭)。 */
const FLAG_DEFAULTS: Record<FlagKey, boolean> = {
  [FLAGS.NEW_CHECKOUT_FLOW]: false,
  [FLAGS.RERANK_V3]: false,
  [FLAGS.AVATAR_LAZY_LOAD]: false,
};

// ============================================================================
// 2. 评估上下文:决定某用户/请求是否命中
// ============================================================================
export interface EvalContext {
  userId?: string;
  /** 内部团队成员标记,用于"先对团队开" */
  isTeamMember?: boolean;
  /** 任意自定义维度:地区、计划、设备等 */
  attributes?: Record<string, string | number | boolean>;
}

// ============================================================================
// 3. Provider 适配器接口 — 换厂商只动这一层
// ============================================================================
export interface FlagProvider {
  /** 布尔开关(含灰度百分比由 provider 内部按 userId 哈希决定) */
  isEnabled(key: FlagKey, ctx: EvalContext, fallback: boolean): Promise<boolean>;
  /** A/B / 多臂实验:返回命中的变体名(如 'control' | 'treatment') */
  getVariant(key: FlagKey, ctx: EvalContext, fallback: string): Promise<string>;
  /** 用于优雅停机 */
  shutdown?(): Promise<void>;
}

// ----------------------------------------------------------------------------
// 3a. Statsig 适配器(默认)
// ----------------------------------------------------------------------------
export class StatsigProvider implements FlagProvider {
  // 这里用动态导入,避免没装 statsig 的环境(如纯前端打包)报错。
  private statsig: any;
  private ready: Promise<void>;

  constructor(private serverSecret: string) {
    this.ready = this.init();
  }

  private async init() {
    const Statsig = (await import('statsig-node')).default;
    await Statsig.initialize(this.serverSecret, { environment: { tier: process.env.NODE_ENV } });
    this.statsig = Statsig;
  }

  private toUser(ctx: EvalContext) {
    return {
      userID: ctx.userId ?? 'anonymous',
      custom: { isTeamMember: ctx.isTeamMember ?? false, ...ctx.attributes },
    };
  }

  async isEnabled(key: FlagKey, ctx: EvalContext, fallback: boolean): Promise<boolean> {
    try {
      await this.ready;
      // 先对团队开:团队成员直接放行,不受百分比限制
      if (ctx.isTeamMember) return true;
      return this.statsig.checkGate(this.toUser(ctx), key);
    } catch (err) {
      console.error(`[flags] isEnabled(${key}) failed, fail-safe -> ${fallback}`, err);
      return fallback; // fail-safe:绝不因开关系统故障而崩主流程
    }
  }

  async getVariant(key: FlagKey, ctx: EvalContext, fallback: string): Promise<string> {
    try {
      await this.ready;
      const exp = this.statsig.getExperiment(this.toUser(ctx), key);
      return exp.get('variant', fallback) as string;
    } catch (err) {
      console.error(`[flags] getVariant(${key}) failed, fail-safe -> ${fallback}`, err);
      return fallback;
    }
  }

  async shutdown() {
    try { await this.statsig?.shutdown(); } catch { /* noop */ }
  }
}

// ----------------------------------------------------------------------------
// 3b. 本地/离线适配器:由环境变量或内存配置驱动。
//     用于本地开发、测试、以及没有外部 provider 时的兜底。
//     灰度百分比用 userId 的稳定哈希实现(同一用户结果稳定)。
// ----------------------------------------------------------------------------
export interface LocalRule {
  enabled: boolean;        // 总开关 / kill switch:false = 杀掉
  rolloutPct?: number;     // 0~100,灰度百分比(默认 100)
  teamOnly?: boolean;      // 仅对团队开
  variantWeights?: Record<string, number>; // A/B 变体权重
}

export class LocalProvider implements FlagProvider {
  constructor(private rules: Partial<Record<FlagKey, LocalRule>> = {}) {}

  private hashPct(seed: string): number {
    // FNV-1a 32-bit,稳定且无依赖
    let h = 0x811c9dc5;
    for (let i = 0; i < seed.length; i++) {
      h ^= seed.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    return (h >>> 0) % 100;
  }

  async isEnabled(key: FlagKey, ctx: EvalContext, fallback: boolean): Promise<boolean> {
    const rule = this.rules[key];
    if (!rule) return fallback;
    if (!rule.enabled) return false;              // kill switch
    if (rule.teamOnly) return !!ctx.isTeamMember;
    if (ctx.isTeamMember) return true;            // 团队总是先拿到
    const pct = rule.rolloutPct ?? 100;
    if (pct >= 100) return true;
    if (pct <= 0) return false;
    return this.hashPct(`${key}:${ctx.userId ?? 'anon'}`) < pct;
  }

  async getVariant(key: FlagKey, ctx: EvalContext, fallback: string): Promise<string> {
    const rule = this.rules[key];
    if (!rule?.variantWeights) return fallback;
    const entries = Object.entries(rule.variantWeights);
    const total = entries.reduce((s, [, w]) => s + w, 0) || 1;
    let bucket = this.hashPct(`${key}:variant:${ctx.userId ?? 'anon'}`) / 100 * total;
    for (const [name, w] of entries) {
      if (bucket < w) return name;
      bucket -= w;
    }
    return fallback;
  }
}

// ============================================================================
// 4. 门面(Facade):业务代码只跟它打交道
// ============================================================================
class FeatureFlags {
  private provider: FlagProvider;

  constructor(provider?: FlagProvider) {
    // 默认:有 STATSIG_SERVER_SECRET 用 Statsig,否则用本地 provider(读环境变量灰度配置)
    if (provider) {
      this.provider = provider;
    } else if (process.env.STATSIG_SERVER_SECRET) {
      this.provider = new StatsigProvider(process.env.STATSIG_SERVER_SECRET);
    } else {
      this.provider = new LocalProvider(loadLocalRulesFromEnv());
    }
  }

  /** 功能是否对该上下文开启。第二参 fallback 默认取登记的保守默认值。 */
  async isEnabled(key: FlagKey, ctx: EvalContext = {}, fallback = FLAG_DEFAULTS[key]) {
    return this.provider.isEnabled(key, ctx, fallback);
  }

  /** A/B 变体。 */
  async getVariant(key: FlagKey, ctx: EvalContext = {}, fallback = 'control') {
    return this.provider.getVariant(key, ctx, fallback);
  }

  async shutdown() { await this.provider.shutdown?.(); }
}

/**
 * 从环境变量加载本地灰度规则,形如:
 *   FLAG_new_checkout_flow='{"enabled":true,"rolloutPct":25}'
 *   FLAG_rerank_v3='{"enabled":false}'   // kill switch 关闭
 * 这样运维可在不改代码、甚至不部署的情况下调灰度(配合 secrets/配置热加载)。
 */
function loadLocalRulesFromEnv(): Partial<Record<FlagKey, LocalRule>> {
  const rules: Partial<Record<FlagKey, LocalRule>> = {};
  for (const key of Object.values(FLAGS)) {
    const raw = process.env[`FLAG_${key}`];
    if (raw) {
      try { rules[key] = JSON.parse(raw) as LocalRule; }
      catch { console.error(`[flags] 无法解析 FLAG_${key}`); }
    }
  }
  return rules;
}

// 单例,业务代码 import 即用
export const flags = new FeatureFlags();

// ============================================================================
// 用法示例
// ============================================================================
//
//   import { flags, FLAGS } from './flags/feature-flags';
//
//   // 新功能路径:把功能藏在开关后(架构师任务模板第 5 节要求)
//   if (await flags.isEnabled(FLAGS.NEW_CHECKOUT_FLOW, { userId, isTeamMember })) {
//     return newCheckout();
//   }
//   return legacyCheckout();
//
//   // A/B:走同一套系统
//   const variant = await flags.getVariant(FLAGS.NEW_CHECKOUT_FLOW, { userId });
//   track('checkout_view', { variant });
//
// 发布节奏(对应手册第 4.5 节):
//   1) teamOnly:true            → 仅团队
//   2) rolloutPct: 5 → 25 → 50  → 灰度放量,盯指标
//   3) rolloutPct: 100          → 全量
//   4) enabled: false           → kill switch,即时关闭、无需部署
