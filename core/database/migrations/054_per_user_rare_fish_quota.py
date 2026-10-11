"""
迁移 054：稀有鱼配额从「全服共享池」改为「人均每日配额」

背景（用户反馈：稀有鱼数量太少，玩的人多了根本不够钓）
------------------------------------------------------
原设计的稀有鱼配额（4星及以上）是 `fishing_zones.rare_fish_caught_today` 这个
**区域级全局计数器**：
- 判定：zone.rare_fish_caught_today < zone.daily_rare_fish_quota
- 自增：任意玩家钓到一条 4星+ 就全局 +1

即整个服务器共享一个池子。钓鱼的人越多，池子越快被前排玩家抽干；
一旦打满，所有玩家都只能钓到 1-3 星鱼——与「人均可钓量」的目标完全背离，
人数一多就人人无鱼可钓。原各区配额（区1=50/区2=200/区3=100/区4=30）本就是
按单人日均设计的，套在全局池上严重不足。

修复
----
1. 新增 `user_daily_rare_fish` 表：按 (user_id, date, zone_id) 记录**每玩家每日每区**
   的 4星+ 渔获数。`date` 取「刷新日」（与全局 daily_reset_hour 对齐，见
   fishing_service.get_last_reset_time），跨刷新点自动进入新日、计数归零，
   因此不需要额外的定时重置任务，且与全局刷新周期严格一致。
2. 配额语义由「全服共享」改为「人均」：`fishing_zones.daily_rare_fish_quota`
   列保留（不破坏 schema 与后台可调性），但其含义变为「单个玩家每日在该区
   可钓的 4星+ 鱼上限」，由 go_fish 用「玩家当日计数」而非全局计数来判定。

配额档位（人均宽松上限，按各区自然稀有率标定，正常玩家基本碰不到天花板）
--------------------------------------------------------------------
- 区1 新手港湾(4星+≈2%)   : 40
- 区2 深海峡谷(4星+≈10%)  : 60
- 区3 传说之海(4星+≈30%)  : 100
- 区4 无尽深渊(4星+≈65%)  : 150
- 区5 救济港湾            : 0（本就只出 1-2 星，不变）
这些值只作为存量库的兜底默认值写入；运营仍可直接编辑 fishing_zones 表调整。
"""

import sqlite3

from astrbot.api import logger

# (zone_id, 人均每日配额)
PER_USER_QUOTAS = (
    (1, 40),
    (2, 60),
    (3, 100),
    (4, 150),
    (5, 0),
)


def up(cursor: sqlite3.Cursor):
    logger.info("正在执行 054_per_user_rare_fish_quota: 稀有鱼配额改为人均每日配额...")

    # 1) 按玩家×刷新日×区域 的每日稀有鱼计数表
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_daily_rare_fish (
            user_id TEXT NOT NULL,
            date TEXT NOT NULL,
            zone_id INTEGER NOT NULL,
            rare_fish_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, date, zone_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_daily_rare_fish_user_date
        ON user_daily_rare_fish (user_id, date)
        """
    )
    logger.info("  已创建（或复用）user_daily_rare_fish 表 + 索引")

    # 2) 把各区 daily_rare_fish_quota 刷成人均档位
    for zone_id, quota in PER_USER_QUOTAS:
        cursor.execute(
            "UPDATE fishing_zones SET daily_rare_fish_quota = ? WHERE id = ?",
            (quota, zone_id),
        )
    logger.info(
        "  已将各区 daily_rare_fish_quota 刷为人均档位："
        + ", ".join(f"区{z}={q}" for z, q in PER_USER_QUOTAS)
    )

    # 3) 全局计数器归零（语义已废弃，仅保留兼容；go_fish 不再依赖它做判定）
    cursor.execute("UPDATE fishing_zones SET rare_fish_caught_today = 0")
    logger.info("  已将各区全局 rare_fish_caught_today 归零（不再用于判定）")

    logger.info("稀有鱼人均配额改造完成——人数增加不再互相抢配额。")


def down(cursor: sqlite3.Cursor):
    logger.info("正在回滚 054_per_user_rare_fish_quota...")
    try:
        # 恢复原全服共享配额默认值
        original = ((1, 50), (2, 200), (3, 100), (4, 30), (5, 0))
        for zone_id, quota in original:
            cursor.execute(
                "UPDATE fishing_zones SET daily_rare_fish_quota = ? WHERE id = ?",
                (quota, zone_id),
            )
        cursor.execute("DROP TABLE IF EXISTS user_daily_rare_fish")
        logger.info("已恢复全服共享配额并删除 user_daily_rare_fish 表。")
    except Exception as e:
        logger.error(f"回滚 054 失败: {e}")
        raise