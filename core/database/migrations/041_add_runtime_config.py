"""
迁移 041：运营配置覆盖表（runtime_config）

背景
----
`_conf_schema.json` 提供了配置的**默认值**，但运营期需要随时在线调整数值
（活动倍率、定价、成功率等），重启插件又太慢。本迁移新增一张覆盖表，
用于持久化「后台下发的配置值」，启动时由 ConfigService 合并进 game_config。

设计要点
--------
1. **只存覆盖项**：未出现在表中的配置沿用默认值，避免把全部默认值冗余写入。
2. **key 使用点号路径**：如 `fishing.base_success_rate`，便于按前缀批量查询/重置。
3. **保留操作痕迹**：记录 updated_by 与 updated_at，便于追溯是谁改的。
4. **is_active 开关**：可以临时禁用某条覆盖而不删除，便于活动结束快速回滚。
"""

import sqlite3

from astrbot.api import logger


def up(cursor: sqlite3.Cursor):
    logger.info("正在执行 041_add_runtime_config: 创建运营配置覆盖表...")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_key TEXT NOT NULL UNIQUE,   -- 点号路径，如 fishing.base_success_rate
            config_value TEXT,                 -- 统一以 JSON 字符串存储（数字/布尔/对象均可）
            value_type TEXT DEFAULT 'string',  -- string/int/float/bool/json，仅用于展示与筛选
            category TEXT,                     -- 所属配置块，便于后台分组展示
            description TEXT,                  -- 配置项说明
            is_active BOOLEAN DEFAULT TRUE NOT NULL,  -- 是否启用该覆盖
            updated_by TEXT,                   -- 最后一次修改的操作者
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_config_key ON runtime_config(config_key)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_config_category ON runtime_config(category)"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_config_key_active "
        "ON runtime_config(config_key) WHERE is_active = TRUE"
    )

    # 预置运营可调项的元信息（config_value 为 NULL 表示沿用默认值，仅登记说明）
    # 这样后台首次进入配置中心即可看到「哪些项可以在线调」，而不是一张空表。
    presets = [
        ("fishing.base_success_rate", "float", "fishing", "钓鱼基础成功率（0.0-1.0）"),
        ("fishing.cooldown_seconds", "int", "fishing", "钓鱼冷却时间（秒）"),
        ("fishing.quality_bonus_max_chance", "float", "fishing", "高品质鱼最大触发概率"),
        ("fishing.rare_chance_max_boost", "float", "fishing", "稀有鱼加成的最大生效比例"),
        ("tax.threshold", "int", "tax", "税收起征点"),
        ("tax.max_rate", "float", "tax", "最大税率"),
        ("market.listing_tax_rate", "float", "market", "市场上架税率"),
        ("signin.min_reward", "int", "signin", "签到金币奖励下限"),
        ("signin.max_reward", "int", "signin", "签到金币奖励上限"),
        ("signin.premium_reward", "int", "signin", "每日签到获得的高级货币"),
        ("wipe_bomb.max_attempts_per_day", "int", "wipe_bomb", "每日擦弹次数上限"),
        ("wipe_bomb.suppression_threshold", "float", "wipe_bomb", "服务器抑制触发倍率"),
        ("refine.costs", "json", "refine", "精炼费用表（1-10 级）"),
        ("refine.success_rates", "json", "refine", "精炼成功率表（按稀有度分档）"),
        ("refine.cost_multipliers", "json", "refine", "精炼费用系数（按稀有度分档）"),
        ("refine.downgrade_chance", "float", "refine", "精炼失败降级概率"),
        ("refine.destruction_chances", "json", "refine", "精炼失败毁坏概率（按稀有度分档）"),
        ("refine.max_level", "int", "refine", "精炼等级上限"),
    ]
    cursor.executemany(
        """
        INSERT OR IGNORE INTO runtime_config
            (config_key, config_value, value_type, category, description, is_active)
        VALUES (?, NULL, ?, ?, ?, TRUE)
        """,
        [(k, t, c, d) for k, t, c, d in presets],
    )

    logger.info(f"运营配置覆盖表创建完成，预置 {len(presets)} 个可调项元信息。")


def down(cursor: sqlite3.Cursor):
    logger.info("正在回滚 041_add_runtime_config...")
    try:
        cursor.execute("DROP TABLE IF EXISTS runtime_config")
        logger.info("运营配置覆盖表已删除")
    except Exception as e:
        logger.error(f"回滚 041 失败: {e}")
        raise