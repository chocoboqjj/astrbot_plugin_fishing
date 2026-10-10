"""
迁移 046：新增「救济港湾」破产安全网区域

背景
----
玩家通过擦弹 / 税收等机制可能把金币打到 0，而最便宜的普通区（区域一）也要 10 金币，
导致「0 金币 + 当日已签到 + 无鱼无装备可卖」的玩家被临时卡死，只能等次日签到才能恢复。
这是一个真实发生的体验断层（用户亲历：擦弹归零后无处钓鱼）。

设计
----
新增区域 5「救济港湾」作为免费安全网：
- fishing_cost = 0：破产玩家也能钓。
- 稀有度分布仅 1-2 星（垃圾小鱼）：产出低，自然引导玩家恢复后回普通区。
- 无通行证、无稀有鱼配额、无时间限制：任何破产玩家都可立即进入。
- 进入门槛由 config_defaults / _conf_schema 的 relief_zone.coin_threshold 控制
  （默认 100）：金币低于阈值才可进入，恢复超过后禁止再进 —— 防止土豪白嫖刷钱。

注意
----
1. 本迁移仅负责把区域写进 fishing_zones 表；判定逻辑（门槛 / 是否启用）在
   fishing_service.set_user_fishing_zone / go_fish 中读取 game_config["relief_zone"]。
2. 若区域 5 已存在（重复执行或管理员自建），则跳过创建，不覆盖任何已有配置。
3. 区域 5 的 rarity_distribution 为 6 元素标准长度 [1星…6+星]，
   与 fishing_zone_service 的 _normalize_distribution 约定一致。
"""

import sqlite3

from astrbot.api import logger

ZONE_ID = 5
ZONE_NAME = "救济港湾"
ZONE_DESC = (
    "专为破产渔夫开放的免费安全网海域，只产出 1-2 星小鱼。"
    "钓到的鱼可出售换金币恢复元气。仅当金币低于阈值时可进入。"
)

# 稀有度分布：[1星, 2星, 3星, 4星, 5星, 6星及以上]
# 全部权重压在 1-2 星，3 星及以上为 0 —— 救济区只出垃圾小鱼，杜绝刷高价值鱼。
RARITY_DISTRIBUTION = [0.80, 0.20, 0.0, 0.0, 0.0, 0.0]
FISHING_COST = 0
DAILY_QUOTA = 0


def up(cursor: sqlite3.Cursor):
    logger.info("正在执行 046_add_relief_zone: 新增破产救济区...")

    # 幂等：区域 5 已存在则跳过，绝不覆盖管理员在后台做的调整
    cursor.execute("SELECT id FROM fishing_zones WHERE id = ?", (ZONE_ID,))
    if cursor.fetchone():
        logger.info(f"  区域{ZONE_ID} 已存在，跳过创建。")
        return

    configs = (
        '{"rarity_distribution": ['
        + ", ".join(str(v) for v in RARITY_DISTRIBUTION)
        + "]}"
    )
    cursor.execute(
        """
        INSERT INTO fishing_zones
            (id, name, description, daily_rare_fish_quota, rare_fish_caught_today,
             configs, is_active, available_from, available_until,
             required_item_id, requires_pass, fishing_cost)
        VALUES (?, ?, ?, ?, 0, ?, 1, NULL, NULL, NULL, 0, ?)
        """,
        (
            ZONE_ID,
            ZONE_NAME,
            ZONE_DESC,
            DAILY_QUOTA,
            configs,
            FISHING_COST,
        ),
    )
    logger.info(
        f"  已创建区域{ZONE_ID}「{ZONE_NAME}」："
        f"免费(fishing_cost={FISHING_COST})、仅1-2星小鱼、无通行证、配额{DAILY_QUOTA}/天"
    )
    logger.info("破产救济区创建完成——0 金币玩家现在可 /钓鱼区域 5 免费恢复。")


def down(cursor: sqlite3.Cursor):
    logger.info("正在回滚 046_add_relief_zone...")
    try:
        # 直接删除救济区（不影响 1-4 区，也不影响玩家数据；玩家若正停在该区会被 go_fish 自动送回区域一）
        cursor.execute("DELETE FROM fishing_zones WHERE id = ?", (ZONE_ID,))
        logger.info(f"区域{ZONE_ID} 已删除（救济区功能关闭）。")
    except Exception as e:
        logger.error(f"回滚 046 失败: {e}")
        raise
