"""配置默认值与容错读取工具。

本模块集中管理「后台/框架未下发配置时」的兜底默认值，并提供类型安全的配置读取函数。

设计目标
--------
1. **单一事实来源**：所有配置项的默认值只在此定义一次，避免散落在各个 Service 的
   ``config.get(key, default)`` 调用点中，导致默认值互相冲突。
2. **类型容错**：从 JSON / WebUI 读到的配置可能为 ``None``、空字典、字符串等异常类型，
   ``safe_get`` / ``safe_get_nested`` 会自动回退到默认值，不会抛出异常。
3. **向后兼容**：现有 Service 仍可继续使用原生 ``.get()``；本模块的默认值会在
   ``main.py`` 组装 ``game_config`` 时被合并进去，从而在不改动 Service 的前提下补全配置。

数据流
------
``_conf_schema.json`` → ``AstrBotConfig`` → :func:`build_game_config` → ``game_config`` → 各个 Service
"""

import json
from typing import Any, Dict, List, Mapping, Optional

from astrbot.api import logger

# ==========================================================
# 类型安全的读取工具
# ==========================================================


def safe_get(config: Any, key: str, default: Any = None) -> Any:
    """从配置字典中安全取值。

    当 ``config`` 不是字典（例如为 ``None`` 或被错误配置成字符串）时，直接返回默认值。
    """
    if not isinstance(config, Mapping):
        return default
    value = config.get(key, default)
    # 显式配置了 None 时也回退到默认值，避免下游拿到 None 后崩溃
    return default if value is None else value


def safe_get_nested(config: Any, *keys: str, default: Any = None) -> Any:
    """按路径安全读取嵌套配置，例如 ``safe_get_nested(cfg, "tax", "threshold", default=1000)``。

    任意一层缺失或类型异常时，返回 ``default``。
    """
    current: Any = config
    for key in keys:
        if not isinstance(current, Mapping):
            return default
        if key not in current:
            return default
        current = current[key]
    return default if current is None else current


def coerce_int(value: Any, default: int, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    """将配置值强制转换为 int，失败或越界时返回 ``default``。"""
    result: int
    if isinstance(value, bool):
        # bool 是 int 的子类，单独处理避免 True 被当作 1
        result = default
    elif isinstance(value, int):
        result = value
    elif isinstance(value, float):
        result = int(value)
    elif isinstance(value, str):
        try:
            result = int(value.strip())
        except (TypeError, ValueError):
            logger.warning(f"[CONFIG] 配置项 {value!r} 无法解析为整数，使用默认值 {default}")
            result = default
    else:
        result = default

    if minimum is not None and result < minimum:
        logger.warning(f"[CONFIG] 配置项 {result} 小于下限 {minimum}，已修正为下限")
        result = minimum
    if maximum is not None and result > maximum:
        logger.warning(f"[CONFIG] 配置项 {result} 超过上限 {maximum}，已修正为上限")
        result = maximum
    return result


def coerce_float(value: Any, default: float, minimum: Optional[float] = None, maximum: Optional[float] = None) -> float:
    """将配置值强制转换为 float，失败或越界时返回 ``default``。"""
    result: float
    if isinstance(value, bool):
        result = default
    elif isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        try:
            result = float(value.strip())
        except (TypeError, ValueError):
            logger.warning(f"[CONFIG] 配置项 {value!r} 无法解析为浮点数，使用默认值 {default}")
            result = default
    else:
        result = default

    if minimum is not None and result < minimum:
        logger.warning(f"[CONFIG] 配置项 {result} 小于下限 {minimum}，已修正为下限")
        result = minimum
    if maximum is not None and result > maximum:
        logger.warning(f"[CONFIG] 配置项 {result} 超过上限 {maximum}，已修正为上限")
        result = maximum
    return result


def coerce_bool(value: Any, default: bool) -> bool:
    """将配置值强制转换为 bool。支持 "true"/"1"/"on" 等常见字符串写法。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1", "yes", "on"):
            return True
        if normalized in ("false", "0", "no", "off"):
            return False
    return default


def merge_defaults(target: Any, defaults: Mapping[str, Any]) -> Dict[str, Any]:
    """把默认值递归合并到配置字典中（仅补齐缺失项，不覆盖已下发的值）。

    这样即使后台只下发了一部分配置，游戏也能以完整的默认配置正常启动。
    """
    if not isinstance(target, Mapping):
        target = {}
    merged: Dict[str, Any] = dict(target)
    for key, default_value in defaults.items():
        if key not in merged or merged[key] is None:
            merged[key] = default_value
        elif isinstance(default_value, Mapping) and isinstance(merged[key], Mapping):
            merged[key] = merge_defaults(merged[key], default_value)
    return merged


# ==========================================================
# 配置默认值定义（单一事实来源）
# ==========================================================

# --- 税收系统 ---
# 设计原则
# --------
# 税收是**存量税**（按持有额一次性征收），不是日流量税，
# 因此判断标准应是「税额 / 日产出」的相对比例，而非绝对值。
#
# 历史设定（起征100万 / 步长10万涨1% / 上限20%）存在三个问题：
#   1. 阶梯太陡：0.1% → 20% 仅 20 个台阶，持有 300 万即封顶 20%
#   2. 起征点过低：区域3 日均产出已达 40 万，持有刚过 100 万就开始重税，
#      高效玩家 2~3 天积累会被全部吃光
#   3. 惩罚了正确行为：出售 7 星 10 级装备（192 万）要交 38 万税，
#      实质是装备定价的 1.8 倍成本，导致「不敢卖装备」
#
# 新设定（P1，2026-10）：起征 100 万 / 步长 500 万涨 1% / 上限 10%
#   · 持有 < 100 万 → 完全免税，不打扰日常体验
#   · 持有 100 万~600 万 → 0.1% 起点税（数量级等于每日钓鱼零头），构成持续但不痛的抽水
#   · 持有 2600 万 → 税 5.1%，约为区域4 日产出的 1 倍出头，属可调节范围
#   · 持有 5100 万及以上 → 触顶 10% 重税，通胀回收的最后一道闸
#   · 与「付费卡池改为净消耗（P0）」配合，整体把金币流速从放水转为收水
#   · 起征点由 1000 万下调至 100 万，是为解决「中产(<1000万)玩家缺乏持续抽水」的漏洞
DEFAULT_TAX_CONFIG: Dict[str, Any] = {
    "is_tax": True,
    "threshold": 1000000,
    "step_coins": 5000000,
    "step_rate": 0.01,
    "min_rate": 0.001,
    "max_rate": 0.10,
    "transfer_tax_rate": 0.05,
}

# --- 钓鱼系统 ---
DEFAULT_FISHING_CONFIG: Dict[str, Any] = {
    "cost": 10,
    "cooldown_seconds": 180,
    "quality_bonus_max_chance": 0.35,
    # 高品质概率的压缩系数：实际概率 = log2(quality_modifier) × 本系数，并被上���封顶。
    # 历史值 0.175（= 0.35/2）使品质加成成为鸡肋属性（满配仅 4.6%），
    # 现提高到 0.5，使满配（×1.44）可达约 26%，与 rare_chance 形成互补。
    "quality_chance_scale": 0.5,
    # 钓鱼核心概率（原本硬编码在 fishing_service 中，此处开放为可配置）
    "base_success_rate": 0.7,
    # 稀有度权重转移系数与上限
    "rare_chance_transfer_factor": 1.0,
    # 稀有加成封顶：装备满配稀有可达 0.92（鱼竿0.15 + 饰品0.05 + 10级精炼0.72），
    # 历史封顶 0.8 会让精炼 9~10 级的稀有提升完全失效（0.84/0.92 都被截到 0.8），
    # 玩家失去精炼动力。现提高到 1.0，使满配能完整生效，
    # 同时保留上限作为防溢出保护（防止数值被进一步放大后击穿概率分布）。
    "rare_chance_max_boost": 1.0,
    # base_value 低于该值视为垃圾鱼，可被鱼饵修正
    "garbage_fish_value_threshold": 5,
}

# --- 偷鱼 / 电鱼 ---
DEFAULT_STEAL_CONFIG: Dict[str, Any] = {
    "cooldown_seconds": 14400,
}

DEFAULT_ELECTRIC_FISH_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "cooldown_seconds": 7200,
    "base_success_rate": 0.6,
    "failure_penalty_max_rate": 0.5,
    # 电鱼鱼塘数量门槛，低于该值拒绝电鱼
    "min_pond_count": 100,
}

# --- 全局 ---
DEFAULT_GAME_CONFIG: Dict[str, Any] = {
    "daily_reset_hour": 0,
    "wheel_of_fate_daily_limit": 3,
    "wipe_bomb_attempts": 3,
    # 成就检查线程轮询间隔（秒）
    "achievement_check_interval": 600,
    # 自动钓鱼线程轮询间隔（秒）
    "auto_fishing_interval": 40,
    # 每日税收线程轮询间隔（秒）
    "daily_tax_interval": 3600,
}

# --- 签到 ---
DEFAULT_SIGNIN_CONFIG: Dict[str, Any] = {
    "min_reward": 100,
    "max_reward": 300,
    "premium_reward": 1,
    "consecutive_bonuses": {
        "3": 500,
        "7": 1500,
        "15": 5000,
        "30": 15000,
    },
}

# --- 用户 ---
DEFAULT_USER_CONFIG: Dict[str, Any] = {
    "initial_coins": 200,
    "initial_premium_currency": 0,
    "default_pond_capacity": 480,
    "default_aquarium_capacity": 50,
    "nickname_max_length": 32,
}

# --- 市场 ---
DEFAULT_MARKET_CONFIG: Dict[str, Any] = {
    "listing_tax_rate": 0.05,
}

# --- 骰宝（原先完全缺失于 schema，仅靠 Service 内部硬编码兜底） ---
DEFAULT_SICBO_CONFIG: Dict[str, Any] = {
    "countdown_seconds": 60,
    "min_bet": 100,
    "max_bet": 1000000,
    "message_mode": "image",
}

# --- 通知 ---
DEFAULT_NOTIFICATIONS_CONFIG: Dict[str, Any] = {
    "relocation_target": "group",
}

# --- 擦弹 ---
# 权重表结构： (最小倍率, 最大倍率, 整数权重)，三者均为数字；权重总和决定各档位被抽中的相对概率。
DEFAULT_WIPE_BOMB_CONFIG: Dict[str, Any] = {
    "max_attempts_per_day": 3,
    # 运势预知准确率与占卜失败率
    "prediction_accuracy": 0.333,
    "divination_failure_rate": 0.333,
    # 达到该倍率时触发服务器级抑制（避免极端值破坏经济）
    "suppression_threshold": 15.0,
}

# --- 装备出售价格（1-10 星） ---
DEFAULT_SELL_PRICES: Dict[str, Any] = {
    "by_rarity_1": 100,
    "by_rarity_2": 500,
    "by_rarity_3": 2000,
    "by_rarity_4": 5000,
    "by_rarity_5": 10000,
    "by_rarity_6": 20000,
    "by_rarity_7": 50000,
    "by_rarity_8": 100000,
    "by_rarity_9": 200000,
    "by_rarity_10": 500000,
}

# --- 精炼等级对应的售价倍率 ---
# 曲线设计：相邻级固定 ×1.5，10 级累计 38.4 倍。
# 早期版本使用 1.0→660 的指数曲线，导致 7 星装备满级售价达 3.3 亿，
# 单件装备价值超过玩家全部产出，使 10 级精炼既无经济意义也无炫耀价值。
# 新曲线下 7 星满级约 1920 万，仍是长期目标，但不会击穿经济体系。
DEFAULT_REFINE_MULTIPLIERS: Dict[str, float] = {
    "1": 1.0, "2": 1.5, "3": 2.2, "4": 3.4, "5": 5.1,
    "6": 7.6, "7": 11.4, "8": 17.1, "9": 25.6, "10": 38.4,
}

# --- 精炼系统（原先全部硬编码在 inventory_service 中） ---
# 费用表按「相邻级约 2-2.5 倍」递增，1→10 级累计 1889 万金币（7 星装备不打折）。
# 成功率按稀有度分档：低星装备轻松，高星装备在 6 级后跌到 50% 以下。
# 失败后果：降级概率 10%（仅对 5 级以上），毁坏概率仅在精炼等级 >= 5 时才可能出现。
DEFAULT_REFINE_CONFIG: Dict[str, Any] = {
    "max_level": 10,
    # 各级精炼的基础费用（key 为「当前等级 → 精炼到下一级」）
    "costs": {
        "1": 10000, "2": 30000, "3": 50000, "4": 100000,
        "5": 200000, "6": 500000, "7": 1000000, "8": 2000000,
        "9": 5000000, "10": 10000000,
    },
    # 费用系数：按稀有度分档，保证「1→10 级总费用」随星级单调递增。
    # 早期使用 low(<=4)=0.25 单一档位，导致 3 星（成功率中等、尝试次数多）
    # 的总费用反而高于 5 星，出现倒挂。现按 6 档细分消除该问题。
    # 实测总费用：1-2星 3.8M / 3星 5.7M / 4星 7.9M / 5星 11.3M / 6星 15.1M / 7星+ 18.9M
    "cost_multipliers": {
        "1-2": 0.20,
        "3": 0.30,
        "4": 0.42,
        "5": 0.60,
        "6": 0.80,
        "7+": 1.00,
    },
    # 成功率表：key 为稀有度档位，value 为 1~10 级的成功率
    "success_rates": {
        "1-2": [0.95, 0.95, 0.90, 0.90, 0.85, 0.80, 0.75, 0.70, 0.60, 0.50],
        "3":   [0.90, 0.90, 0.85, 0.85, 0.80, 0.75, 0.65, 0.55, 0.45, 0.35],
        "4":   [0.85, 0.85, 0.80, 0.80, 0.75, 0.70, 0.60, 0.50, 0.40, 0.30],
        "5":   [0.85, 0.85, 0.80, 0.75, 0.65, 0.50, 0.40, 0.35, 0.30, 0.25],
        "6":   [0.80, 0.80, 0.75, 0.70, 0.60, 0.45, 0.35, 0.30, 0.25, 0.20],
        "7+":  [0.80, 0.80, 0.80, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.20],
    },
    # 失败为「降级」的概率（不毁坏，仅等级-1）
    "downgrade_chance": 0.10,
    # 失败为「毁坏」的概率，仅当当前精炼等级 >= min_level_for_destruction 时才生效
    "min_level_for_destruction": 5,
    "destruction_chances": {
        "1-2": 0.30,
        "3-4": 0.35,
        "5-6": 0.40,
        "7+": 0.50,
    },
    # 装备加成：每个精炼等级提供的加成比例（按稀有度递减，高星装备加成更保守）
    "bonus_per_level": {
        "1-3": 0.15,
        "4": 0.12,
        "5": 0.08,
        "6": 0.05,
        "7+": 0.03,
    },
}

# --- 钓鱼区域数值 ---
# ⚠️ 重要：本常量目前是「数据库镜像」，运行时并不消费它。
#    区域费用 / 稀有鱼配额的真实生效值来自 fishing_zones 表，
#    由迁移 042（配额）与 045（费用 + 星级分布）写入，并由 fishing_service 直接读库。
#    因此：改这里不会改变游戏行为；要调整区域数值请改迁移或直接改库。
#
# 区域收益预期（已计入 0.7 基础成功率）：
#   区域1 ≈ 39 金币/次  区域2 ≈ 175 金币/次  区域3 ≈ 960 金币/次
# 费用 10 / 100 / 545 / 2130 使回本次数均为 0.1~0.3 次，钓鱼始终是正收益，符合放置游戏预期。
DEFAULT_ZONE_CONFIG: Dict[str, Any] = {
    "1": {"fishing_cost": 10, "daily_rare_fish_quota": 50},
    # 稀有鱼配额说明：配额用于限制 4 星及以上鱼类的每日产出，防止通货膨胀。
    # 费用与迁移 045 保持一致（10 / 100 / 545 / 2130），
    # 该梯度经实测使「每金币产出」严格递减（3.94 / 2.96 / 2.61 / 2.20）。
    "2": {"fishing_cost": 100, "daily_rare_fish_quota": 200},
    "3": {"fishing_cost": 545, "daily_rare_fish_quota": 100},
    "4": {"fishing_cost": 2130, "daily_rare_fish_quota": 30},
}

# --- 鱼塘容量升级阶梯 ---
# 设计依据：每日渔获约 518 条（288 次 × 平均 1.8 条）
# 每档容量对应一个明确的「游戏阶段」，费用涨幅与容量涨幅同阶（约 8~10 倍）：
#   480    →  2,000约 4 天   新手期，够放下第一批收藏
#   2,000  → 20,000  约 39 天  中期主力档，配合区域配额囤稀有鱼
#   20,000 → 200,000 约 386 天 长期档，配额全开后仍有余量
#   200,000→ 1,000,000        收藏级，可容纳全图鉴数量的约 9 倍
#
# 历史设定（480→999→9999→99999→999999，费用 5万/50万/5000万/50亿）的问题：
#   · 容量每档仅涨 10 倍，费用却涨 10x / 100x / 100x，成本与收益脱钩
#   · 480 容量仅 1.1 天就满，新手第一周就要面对「鱼塘爆满」
#   · 末档 50 亿金币，按区域4期望（4690/次）需刷 3.5 万次，完全不可达
DEFAULT_POND_UPGRADES: List[Dict[str, int]] = [
    {"from": 480, "to": 2000, "cost": 50000},
    {"from": 2000, "to": 20000, "cost": 400000},
    {"from": 20000, "to": 200000, "cost": 5000000},
    {"from": 200000, "to": 1000000, "cost": 60000000},
]

# --- 钓鱼阶级系统（段位制 · 纯增益型） ---
# 设计取舍
# --------
# · 段位制：单一纵向阶梯，双门槛自动晋升、只升不降。
# · 双门槛 = 累计钓鱼次数 + 图鉴收集数。自动钓鱼冷却 180s（约 480 次/天），
#   只靠挂机约 31 天即可到 15,000 次；加入图鉴门槛后，高阶被「收集深度」卡住
#   （112 种鱼中的 6★ 稀有鱼极难出），避免纯时长灌满。
# · 纯增益型特权：只给税收折扣 / 商店折扣 / 称号，
#   **不锁定任何已有内容**（区域、鱼塘档位、精炼等级均不受限），老玩家零风险。
#
# 字段说明
#   level         阶级
#   name          阶级名
#   fish_count    累计钓鱼次数门槛
#   pokedex       图鉴收集数门槛
#   title_id      对应称号 ID（由迁移 047 播种，901-909）
#   tax_discount  每日资产税折扣（0.10 = 减税 10%）
#   shop_discount 商店购买折扣（0.05 = 95 折）
#   wipe_bomb_bonus 每日擦弹次数加成
#
# ⚠️ 修改门槛时请同步 core/database/migrations/047_add_fishing_class.py 中的
#    CLASS_TIERS（迁移必须能独立运行，不导入本模块）。
DEFAULT_FISHING_CLASS_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "total_fish_species": 112,      # 图鉴总数，仅用于展示进度
    "score_weights": {              # 钓力值权重（展示/排行用，不作为门槛）
        "fish_count": 1,
        "pokedex": 20,
        "refine": 30,
    },
    "tiers": [
        {"level": 1, "name": "见习钓手", "fish_count": 0,     "pokedex": 0,   "title_id": 901,
         "tax_discount": 0.00, "shop_discount": 0.00, "wipe_bomb_bonus": 0},
        {"level": 2, "name": "初阶钓手", "fish_count": 50,    "pokedex": 5,   "title_id": 902,
         "tax_discount": 0.00, "shop_discount": 0.00, "wipe_bomb_bonus": 0},
        {"level": 3, "name": "熟练钓手", "fish_count": 200,   "pokedex": 15,  "title_id": 903,
         "tax_discount": 0.02, "shop_discount": 0.00, "wipe_bomb_bonus": 1},
        {"level": 4, "name": "资深钓手", "fish_count": 500,   "pokedex": 28,  "title_id": 904,
         "tax_discount": 0.04, "shop_discount": 0.02, "wipe_bomb_bonus": 2},
        {"level": 5, "name": "钓鱼高手", "fish_count": 1200,  "pokedex": 42,  "title_id": 905,
         "tax_discount": 0.06, "shop_discount": 0.03, "wipe_bomb_bonus": 3},
        {"level": 6, "name": "钓鱼大师", "fish_count": 2500,  "pokedex": 58,  "title_id": 906,
         "tax_discount": 0.08, "shop_discount": 0.05, "wipe_bomb_bonus": 4},
        {"level": 7, "name": "钓鱼宗师", "fish_count": 5000,  "pokedex": 74,  "title_id": 907,
         "tax_discount": 0.10, "shop_discount": 0.06, "wipe_bomb_bonus": 5},
        {"level": 8, "name": "传说钓者", "fish_count": 9000,  "pokedex": 90,  "title_id": 908,
         "tax_discount": 0.12, "shop_discount": 0.08, "wipe_bomb_bonus": 6},
        {"level": 9, "name": "钓神",     "fish_count": 15000, "pokedex": 102, "title_id": 909,
         "tax_discount": 0.15, "shop_discount": 0.10, "wipe_bomb_bonus": 8},
    ],
}

# --- 命运之轮 ---
DEFAULT_WHEEL_OF_FATE_CONFIG: Dict[str, Any] = {
    "min_entry_fee": 500,
    "max_entry_fee": 50000,
    "cooldown_seconds": 60,
    "timeout_seconds": 60,
    # 每关：成功率 / 成功倍率
    "levels": [
        {"success_rate": 0.65, "multiplier": 1.55},
        {"success_rate": 0.60, "multiplier": 1.45},
        {"success_rate": 0.55, "multiplier": 1.55},
        {"success_rate": 0.50, "multiplier": 1.70},
        {"success_rate": 0.45, "multiplier": 1.90},
        {"success_rate": 0.40, "multiplier": 2.15},
        {"success_rate": 0.35, "multiplier": 2.50},
        {"success_rate": 0.30, "multiplier": 3.00},
        {"success_rate": 0.25, "multiplier": 3.70},
        {"success_rate": 0.20, "multiplier": 4.80},
    ],
}

# --- 交易所 ---
DEFAULT_EXCHANGE_CONFIG: Dict[str, Any] = {
    "update_timing": "9:00, 15:00, 21:00",
    "account_fee": 100000,
    "capacity": 1000,
    "tax_rate": 0.05,
    "volatility": {
        "dried_fish": 0.08,
        "fish_roe": 0.12,
        "fish_oil": 0.10,
    },
    "event_chance": 0.1,
    "max_change_rate": 0.2,
    "min_price": 1,
    "max_price": 1000000,
    "sentiment_weights": {
        "panic": 0.1,
        "pessimistic": 0.2,
        "neutral": 0.4,
        "optimistic": 0.2,
        "euphoric": 0.1,
    },
    "merge_window_minutes": 30,
    "initial_prices": {
        "dried_fish": 6000,
        "fish_roe": 12000,
        "fish_oil": 10000,
    },
    # 每个大宗商品的行情参数（原先 Service 读取 config["commodities"] 但 schema 中从未下发）
    "commodities": {
        "dried_fish": {"volatility": 0.08, "risk": "稳健型", "min_price": 3000, "max_price": 12000},
        "fish_roe": {"volatility": 0.12, "risk": "高风险", "min_price": 5000, "max_price": 30000},
        "fish_oil": {"volatility": 0.10, "risk": "投机品", "min_price": 4000, "max_price": 25000},
    },
}

# --- Web 后台 ---
DEFAULT_WEBUI_CONFIG: Dict[str, Any] = {
    "port": 7777,
}

# 顶层配置块默认值映射（供 merge_defaults 递归使用）
TOP_LEVEL_DEFAULTS: Dict[str, Any] = {
    "tax": DEFAULT_TAX_CONFIG,
    "fishing": DEFAULT_FISHING_CONFIG,
    "steal": DEFAULT_STEAL_CONFIG,
    "electric_fish": DEFAULT_ELECTRIC_FISH_CONFIG,
    "game": DEFAULT_GAME_CONFIG,
    "signin": DEFAULT_SIGNIN_CONFIG,
    "user": DEFAULT_USER_CONFIG,
    "market": DEFAULT_MARKET_CONFIG,
    "sicbo": DEFAULT_SICBO_CONFIG,
    "notifications": DEFAULT_NOTIFICATIONS_CONFIG,
    "wipe_bomb": DEFAULT_WIPE_BOMB_CONFIG,
    "sell_prices": DEFAULT_SELL_PRICES,
    "wheel_of_fate": DEFAULT_WHEEL_OF_FATE_CONFIG,
    "refine": DEFAULT_REFINE_CONFIG,
    "zones": DEFAULT_ZONE_CONFIG,
    "exchange": DEFAULT_EXCHANGE_CONFIG,
    "webui": DEFAULT_WEBUI_CONFIG,
}


# ==========================================================
# 顶层组装：把框架配置 + 默认值合成为 game_config
# ==========================================================


def build_game_config(config: Any) -> Dict[str, Any]:
    """组装 ``game_config``，供全部 Service 使用。

    该函数保证：

    * 缺失的配置项自动补齐默认值（不依赖 ``_conf_schema.json`` 是否包含该项）；
    * 类型异常的数值被强制修正到合法区间（不会出现负数冷却、税率大于 1 等情况）；
    * 特殊结构的配置（鱼塘升级阶梯、精炼倍率、命运之轮关卡）始终为合法列表/字典。
    """
    if not isinstance(config, Mapping):
        logger.warning("[CONFIG] 插件配置为空或类型异常，全部使用默认配置启动。")
        config = {}

    # 1) 先把缺失的顶层配置块与缺失的键补齐
    merged = merge_defaults(config, TOP_LEVEL_DEFAULTS)

    # 2) 各块的类型修正
    tax = merged.get("tax", {})
    tax["is_tax"] = coerce_bool(safe_get(tax, "is_tax", True), True)
    tax["threshold"] = coerce_int(safe_get(tax, "threshold", 1000000), 1000000, minimum=0)
    tax["step_coins"] = coerce_int(safe_get(tax, "step_coins", 100000), 100000, minimum=1)
    tax["step_rate"] = coerce_float(safe_get(tax, "step_rate", 0.01), 0.01, minimum=0.0, maximum=1.0)
    tax["min_rate"] = coerce_float(safe_get(tax, "min_rate", 0.001), 0.001, minimum=0.0, maximum=1.0)
    tax["max_rate"] = coerce_float(safe_get(tax, "max_rate", 0.2), 0.2, minimum=0.0, maximum=1.0)
    tax["transfer_tax_rate"] = coerce_float(safe_get(tax, "transfer_tax_rate", 0.05), 0.05, minimum=0.0, maximum=1.0)
    # 下限不应高于上限
    if tax["min_rate"] > tax["max_rate"]:
        tax["min_rate"], tax["max_rate"] = tax["max_rate"], tax["min_rate"]

    fishing = merged.get("fishing", {})
    fishing["cost"] = coerce_int(safe_get(fishing, "cost", 10), 10, minimum=0)
    fishing["cooldown_seconds"] = coerce_int(safe_get(fishing, "cooldown_seconds", 180), 180, minimum=0)
    fishing["quality_bonus_max_chance"] = coerce_float(
        safe_get(fishing, "quality_bonus_max_chance", 0.35), 0.35, minimum=0.0, maximum=1.0
    )
    fishing["quality_chance_scale"] = coerce_float(
        safe_get(fishing, "quality_chance_scale", 0.5), 0.5, minimum=0.05, maximum=2.0
    )
    fishing["base_success_rate"] = coerce_float(
        safe_get(fishing, "base_success_rate", 0.7), 0.7, minimum=0.0, maximum=1.0
    )
    fishing["rare_chance_transfer_factor"] = coerce_float(
        safe_get(fishing, "rare_chance_transfer_factor", 1.0), 1.0, minimum=0.0, maximum=10.0
    )
    fishing["rare_chance_max_boost"] = coerce_float(
        safe_get(fishing, "rare_chance_max_boost", 1.0), 1.0, minimum=0.0, maximum=2.0
    )
    fishing["garbage_fish_value_threshold"] = coerce_int(
        safe_get(fishing, "garbage_fish_value_threshold", 5), 5, minimum=0
    )

    steal = merged.get("steal", {})
    steal["cooldown_seconds"] = coerce_int(safe_get(steal, "cooldown_seconds", 14400), 14400, minimum=0)

    electric = merged.get("electric_fish", {})
    electric["enabled"] = coerce_bool(safe_get(electric, "enabled", True), True)
    electric["cooldown_seconds"] = coerce_int(safe_get(electric, "cooldown_seconds", 7200), 7200, minimum=0)
    electric["base_success_rate"] = coerce_float(
        safe_get(electric, "base_success_rate", 0.6), 0.6, minimum=0.0, maximum=1.0
    )
    electric["failure_penalty_max_rate"] = coerce_float(
        safe_get(electric, "failure_penalty_max_rate", 0.5), 0.5, minimum=0.0, maximum=1.0
    )
    electric["min_pond_count"] = coerce_int(safe_get(electric, "min_pond_count", 100), 100, minimum=0)

    game_cfg = merged.get("game", {})
    game_cfg["daily_reset_hour"] = coerce_int(safe_get(game_cfg, "daily_reset_hour", 0), 0, minimum=0, maximum=23)
    game_cfg["wheel_of_fate_daily_limit"] = coerce_int(
        safe_get(game_cfg, "wheel_of_fate_daily_limit", 3), 3, minimum=0
    )
    game_cfg["wipe_bomb_attempts"] = coerce_int(safe_get(game_cfg, "wipe_bomb_attempts", 3), 3, minimum=0)
    game_cfg["achievement_check_interval"] = coerce_int(
        safe_get(game_cfg, "achievement_check_interval", 600), 600, minimum=10
    )
    game_cfg["auto_fishing_interval"] = coerce_int(
        safe_get(game_cfg, "auto_fishing_interval", 40), 40, minimum=1
    )
    game_cfg["daily_tax_interval"] = coerce_int(
        safe_get(game_cfg, "daily_tax_interval", 3600), 3600, minimum=60
    )

    signin = merged.get("signin", {})
    signin["min_reward"] = coerce_int(safe_get(signin, "min_reward", 100), 100, minimum=0)
    signin["max_reward"] = coerce_int(safe_get(signin, "max_reward", 300), 300, minimum=0)
    if signin["min_reward"] > signin["max_reward"]:
        signin["min_reward"], signin["max_reward"] = signin["max_reward"], signin["min_reward"]
    signin["premium_reward"] = coerce_int(safe_get(signin, "premium_reward", 1), 1, minimum=0)
    bonuses = signin.get("consecutive_bonuses")
    if not isinstance(bonuses, Mapping):
        signin["consecutive_bonuses"] = dict(DEFAULT_SIGNIN_CONFIG["consecutive_bonuses"])

    user_cfg = merged.get("user", {})
    user_cfg["initial_coins"] = coerce_int(safe_get(user_cfg, "initial_coins", 200), 200, minimum=0)
    user_cfg["initial_premium_currency"] = coerce_int(
        safe_get(user_cfg, "initial_premium_currency", 0), 0, minimum=0
    )
    user_cfg["default_pond_capacity"] = coerce_int(
        safe_get(user_cfg, "default_pond_capacity", 480), 480, minimum=1
    )
    user_cfg["default_aquarium_capacity"] = coerce_int(
        safe_get(user_cfg, "default_aquarium_capacity", 50), 50, minimum=0
    )
    user_cfg["nickname_max_length"] = coerce_int(
        safe_get(user_cfg, "nickname_max_length", 32), 32, minimum=1, maximum=64
    )

    market_cfg = merged.get("market", {})
    market_cfg["listing_tax_rate"] = coerce_float(
        safe_get(market_cfg, "listing_tax_rate", 0.05), 0.05, minimum=0.0, maximum=1.0
    )

    sicbo_cfg = merged.get("sicbo", {})
    sicbo_cfg["countdown_seconds"] = coerce_int(safe_get(sicbo_cfg, "countdown_seconds", 60), 60, minimum=5, maximum=600)
    sicbo_cfg["min_bet"] = coerce_int(safe_get(sicbo_cfg, "min_bet", 100), 100, minimum=1)
    sicbo_cfg["max_bet"] = coerce_int(safe_get(sicbo_cfg, "max_bet", 1000000), 1000000, minimum=1)
    if sicbo_cfg["min_bet"] > sicbo_cfg["max_bet"]:
        sicbo_cfg["min_bet"], sicbo_cfg["max_bet"] = sicbo_cfg["max_bet"], sicbo_cfg["min_bet"]
    mode = safe_get(sicbo_cfg, "message_mode", "image")
    sicbo_cfg["message_mode"] = mode if mode in ("image", "text") else "image"

    wipe_bomb = merged.get("wipe_bomb", {})
    wipe_bomb["max_attempts_per_day"] = coerce_int(safe_get(wipe_bomb, "max_attempts_per_day", 3), 3, minimum=0)
    wipe_bomb["prediction_accuracy"] = coerce_float(
        safe_get(wipe_bomb, "prediction_accuracy", 0.333), 0.333, minimum=0.0, maximum=1.0
    )
    wipe_bomb["divination_failure_rate"] = coerce_float(
        safe_get(wipe_bomb, "divination_failure_rate", 0.333), 0.333, minimum=0.0, maximum=1.0
    )
    wipe_bomb["suppression_threshold"] = coerce_float(
        safe_get(wipe_bomb, "suppression_threshold", 15.0), 15.0, minimum=1.0
    )

    # 3) 组装最终的 game_config
    sell_prices = merged.get("sell_prices", {})
    rarity_prices: Dict[str, int] = {}
    for rarity in range(1, 11):
        rarity_prices[str(rarity)] = coerce_int(
            safe_get(sell_prices, f"by_rarity_{rarity}", DEFAULT_SELL_PRICES[f"by_rarity_{rarity}"]),
            DEFAULT_SELL_PRICES[f"by_rarity_{rarity}"],
            minimum=0,
        )

    refine_multiplier: Dict[str, float] = {}
    for level in range(1, 11):
        key = str(level)
        refine_multiplier[key] = coerce_float(
            safe_get(sell_prices, f"refine_multiplier_{key}", DEFAULT_REFINE_MULTIPLIERS[key]),
            DEFAULT_REFINE_MULTIPLIERS[key],
            minimum=1.0,
        )

    pond_upgrades = merged.get("pond_upgrades")
    if not isinstance(pond_upgrades, list) or not pond_upgrades:
        pond_upgrades = [dict(item) for item in DEFAULT_POND_UPGRADES]
    else:
        valid_upgrades = []
        for upgrade in pond_upgrades:
            if not isinstance(upgrade, Mapping):
                continue
            if "from" not in upgrade or "to" not in upgrade or "cost" not in upgrade:
                logger.warning(f"[CONFIG] 忽略非法的鱼塘升级配置项: {upgrade!r}")
                continue
            from_cap = coerce_int(upgrade["from"], 0, minimum=0)
            to_cap = coerce_int(upgrade["to"], 0, minimum=0)
            if to_cap <= from_cap:
                logger.warning(f"[CONFIG] 鱼塘升级容量必须递增，已忽略: {upgrade!r}")
                continue
            valid_upgrades.append(
                {
                    "from": from_cap,
                    "to": to_cap,
                    "cost": coerce_int(upgrade["cost"], 0, minimum=0),
                }
            )
        pond_upgrades = valid_upgrades or [dict(item) for item in DEFAULT_POND_UPGRADES]

    # 钓鱼阶级：校验门槛单调性与折扣区间，非法配置整段回退到默认值
    raw_class = merged.get("fishing_class")
    if not isinstance(raw_class, Mapping):
        raw_class = {}
    class_enabled = coerce_bool(raw_class.get("enabled", True), True)
    total_fish_species = coerce_int(
        raw_class.get("total_fish_species", DEFAULT_FISHING_CLASS_CONFIG["total_fish_species"]),
        DEFAULT_FISHING_CLASS_CONFIG["total_fish_species"],
        minimum=1,
    )
    raw_weights = raw_class.get("score_weights")
    score_weights = {}
    default_weights = DEFAULT_FISHING_CLASS_CONFIG["score_weights"]
    if isinstance(raw_weights, Mapping):
        for wkey, wdefault in default_weights.items():
            score_weights[wkey] = coerce_float(raw_weights.get(wkey, wdefault), wdefault, minimum=0.0)
    else:
        score_weights = dict(default_weights)

    # 兼容两种下发形态：后台 schema 生成 {"1": {...}, "2": {...}}，手工配置常写 [{...}, {...}]
    raw_tiers = raw_class.get("tiers")
    if isinstance(raw_tiers, Mapping):
        raw_tiers = [
            raw_tiers[k]
            for k in sorted(raw_tiers, key=lambda x: int(x) if str(x).isdigit() else 0)
        ]
    valid_tiers: List[Dict[str, Any]] = []
    if isinstance(raw_tiers, list):
        prev_count = -1
        prev_pokedex = -1
        for tier in raw_tiers:
            if not isinstance(tier, Mapping):
                continue
            try:
                lv = coerce_int(tier.get("level", 0), 0, minimum=1)
                need_count = coerce_int(tier.get("fish_count", 0), 0, minimum=0)
                need_pokedex = coerce_int(tier.get("pokedex", 0), 0, minimum=0)
            except Exception:
                continue
            # 门槛必须单调不减，否则晋升判定会出现「高阶比低阶更容易达到」
            if need_count < prev_count or need_pokedex < prev_pokedex:
                logger.warning(f"[CONFIG] 钓鱼阶级门槛必须递增，已忽略: {tier!r}")
                continue
            prev_count, prev_pokedex = need_count, need_pokedex
            valid_tiers.append(
                {
                    "level": lv,
                    "name": str(tier.get("name", f"第{lv}阶")),
                    "fish_count": need_count,
                    "pokedex": need_pokedex,
                    "title_id": coerce_int(tier.get("title_id", 0), 0, minimum=0),
                    "tax_discount": min(
                        max(coerce_float(tier.get("tax_discount", 0.0), 0.0, minimum=0.0), 0.0), 0.9
                    ),
                    "shop_discount": min(
                        max(coerce_float(tier.get("shop_discount", 0.0), 0.0, minimum=0.0), 0.0), 0.9
                    ),
                    "wipe_bomb_bonus": coerce_int(tier.get("wipe_bomb_bonus", 0), 0, minimum=0),
                }
            )

    if not valid_tiers:
        fishing_class = {
            "enabled": class_enabled,
            "total_fish_species": total_fish_species,
            "score_weights": score_weights,
            "tiers": [dict(t) for t in DEFAULT_FISHING_CLASS_CONFIG["tiers"]],
        }
        if isinstance(raw_tiers, list) and raw_tiers:
            logger.warning("[CONFIG] 钓鱼阶级配置全部非法，已回退到默认值")
    else:
        fishing_class = {
            "enabled": class_enabled,
            "total_fish_species": total_fish_species,
            "score_weights": score_weights,
            "tiers": valid_tiers,
        }

    wheel = merged.get("wheel_of_fate", {})
    if not isinstance(wheel, Mapping):
        wheel = {}
    wheel = dict(wheel)
    wheel_levels = wheel.get("levels")
    if not isinstance(wheel_levels, list) or not wheel_levels:
        wheel["levels"] = [dict(item) for item in DEFAULT_WHEEL_OF_FATE_CONFIG["levels"]]
    else:
        valid_levels = []
        for level in wheel_levels:
            if not isinstance(level, Mapping) or "success_rate" not in level or "multiplier" not in level:
                logger.warning(f"[CONFIG] 忽略非法的命运之轮关卡配置: {level!r}")
                continue
            valid_levels.append(
                {
                    "success_rate": coerce_float(level["success_rate"], 0.5, minimum=0.0, maximum=1.0),
                    "multiplier": coerce_float(level["multiplier"], 1.0, minimum=1.0),
                }
            )
        wheel["levels"] = valid_levels or [dict(item) for item in DEFAULT_WHEEL_OF_FATE_CONFIG["levels"]]
    for key, fallback in (
        ("min_entry_fee", 500),
        ("max_entry_fee", 50000),
        ("cooldown_seconds", 60),
        ("timeout_seconds", 60),
    ):
        wheel[key] = coerce_int(safe_get(wheel, key, fallback), fallback, minimum=0)

    notifications = merged.get("notifications")
    if not isinstance(notifications, Mapping):
        notifications = dict(DEFAULT_NOTIFICATIONS_CONFIG)
    notifications = dict(notifications)
    notifications["relocation_target"] = (
        safe_get(notifications, "relocation_target", "group")
        if safe_get(notifications, "relocation_target", "group") in ("group", "private")
        else "group"
    )

    exchange_cfg = merged.get("exchange")
    if not isinstance(exchange_cfg, Mapping):
        exchange_cfg = dict(DEFAULT_EXCHANGE_CONFIG)

    # 交易所配置类型加固：initial_prices / volatility / sentiment_weights 必须是字典
    exchange_out = dict(exchange_cfg)
    for key in ("initial_prices", "volatility", "sentiment_weights", "commodities"):
        if not isinstance(exchange_out.get(key), Mapping):
            if exchange_out.get(key) is not None:
                logger.warning(f"[CONFIG] exchange.{key} 类型异常，已回退默认值")
            exchange_out[key] = json.loads(json.dumps(DEFAULT_EXCHANGE_CONFIG[key]))
    # 价格类数值钳制，防止负数或超大价格破坏行情
    initial_prices = {}
    for cid, fallback in DEFAULT_EXCHANGE_CONFIG["initial_prices"].items():
        initial_prices[cid] = coerce_int(
            safe_get(exchange_out["initial_prices"], cid, fallback), fallback, minimum=1
        )
    exchange_out["initial_prices"] = initial_prices
    for key, fallback in (
        ("account_fee", 100000),
        ("capacity", 1000),
        ("merge_window_minutes", 30),
    ):
        exchange_out[key] = coerce_int(safe_get(exchange_out, key, fallback), fallback, minimum=0)
    for key, fallback in (
        ("tax_rate", 0.05),
        ("event_chance", 0.1),
        ("max_change_rate", 0.2),
    ):
        exchange_out[key] = coerce_float(safe_get(exchange_out, key, fallback), fallback, minimum=0.0, maximum=1.0)
    exchange_out["min_price"] = coerce_int(safe_get(exchange_out, "min_price", 1), 1, minimum=1)
    exchange_out["max_price"] = coerce_int(safe_get(exchange_out, "max_price", 1000000), 1000000, minimum=1)
    if exchange_out["min_price"] > exchange_out["max_price"]:
        exchange_out["min_price"], exchange_out["max_price"] = exchange_out["max_price"], exchange_out["min_price"]

    # 精炼系统配置：结构校验 + 数值钳制
    refine_cfg = merged.get("refine")
    if not isinstance(refine_cfg, Mapping):
        refine_cfg = {}
    refine_out = json.loads(json.dumps(DEFAULT_REFINE_CONFIG))
    refine_out.update({k: v for k, v in refine_cfg.items() if k not in ("costs", "success_rates",
                                                                    "cost_multipliers", "downgrade_chance",
                                                                    "min_level_for_destruction",
                                                                    "destruction_chances", "bonus_per_level",
                                                                    "max_level")})
    refine_out["max_level"] = coerce_int(safe_get(refine_cfg, "max_level", 10), 10, minimum=1, maximum=20)
    refine_out["downgrade_chance"] = coerce_float(
        safe_get(refine_cfg, "downgrade_chance", 0.10), 0.10, minimum=0.0, maximum=1.0
    )
    refine_out["min_level_for_destruction"] = coerce_int(
        safe_get(refine_cfg, "min_level_for_destruction", 5), 5, minimum=1
    )
    if isinstance(refine_cfg.get("costs"), Mapping):
        refine_out["costs"] = {
            str(k): coerce_int(v, 0, minimum=0) for k, v in refine_cfg["costs"].items()
        }
    if isinstance(refine_cfg.get("success_rates"), Mapping):
        rates = {}
        for tier, seq in refine_cfg["success_rates"].items():
            if isinstance(seq, (list, tuple)):
                rates[str(tier)] = [coerce_float(x, 0.5, minimum=0.0, maximum=1.0) for x in seq]
        if rates:
            refine_out["success_rates"] = rates
    if isinstance(refine_cfg.get("cost_multipliers"), Mapping):
        refine_out["cost_multipliers"] = {
            str(k): coerce_float(v, 1.0, minimum=0.0, maximum=10.0)
            for k, v in refine_cfg["cost_multipliers"].items()
        }
    if isinstance(refine_cfg.get("destruction_chances"), Mapping):
        refine_out["destruction_chances"] = {
            str(k): coerce_float(v, 0.0, minimum=0.0, maximum=1.0)
            for k, v in refine_cfg["destruction_chances"].items()
        }
    if isinstance(refine_cfg.get("bonus_per_level"), Mapping):
        refine_out["bonus_per_level"] = {
            str(k): coerce_float(v, 0.0, minimum=0.0, maximum=1.0)
            for k, v in refine_cfg["bonus_per_level"].items()
        }

    game_config: Dict[str, Any] = {
        "fishing": dict(fishing),
        "quality_bonus_max_chance": fishing["quality_bonus_max_chance"],
        "steal": dict(steal),
        "electric_fish": dict(electric),
        "wipe_bomb": dict(wipe_bomb),
        "wheel_of_fate_daily_limit": game_cfg["wheel_of_fate_daily_limit"],
        "daily_reset_hour": game_cfg["daily_reset_hour"],
        "game": dict(game_cfg),
        "achievement_check_interval": game_cfg["achievement_check_interval"],
        "auto_fishing_interval": game_cfg["auto_fishing_interval"],
        "daily_tax_interval": game_cfg["daily_tax_interval"],
        "user": dict(user_cfg),
        "market": dict(market_cfg),
        "signin": dict(signin),
        "sicbo": dict(sicbo_cfg),
        "notifications": notifications,
        "tax": dict(tax),
        "pond_upgrades": pond_upgrades,
        "fishing_class": fishing_class,
        "wheel_of_fate": dict(wheel),
        "refine": refine_out,
        "zones": merged.get("zones") if isinstance(merged.get("zones"), Mapping) else dict(DEFAULT_ZONE_CONFIG),
        "sell_prices": {
            "rod": dict(rarity_prices),
            "accessory": dict(rarity_prices),
            "refine_multiplier": refine_multiplier,
        },
        "exchange": exchange_out,
    }

    logger.info(
        "[CONFIG] 配置装配完成："
        f"税收={'开' if tax['is_tax'] else '关'}, "
        f"钓鱼CD={fishing['cooldown_seconds']}s, "
        f"鱼塘升级档位={len(pond_upgrades)}, "
        f"交易所商品={len(game_config['exchange'].get('commodities', {}))}种"
    )
    return game_config