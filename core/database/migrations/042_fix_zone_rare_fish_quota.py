"""
迁移 042：修正钓鱼区域的稀有鱼配额

背景
----
迁移 005 设定的配额为 区域1=50、区域2=2000、区域3=500。区域2 反而是区域1 的 40 倍，
且区域3 低于区域2 —— 与「区域越难、稀有鱼配额越宽松」的设计意图完全相反，
使配额机制失去了调控通胀的意义（实测区域2 每日可产出 2000 条 4 星以上鱼）。

修正为 50 / 200 / 100：
* 区域1（新手）：50，保持不变，仍是最严格的稀缺区。
* 区域2（深海峡谷）：2000 → 200，对齐其收益水平（期望 175 金币/次）。
* 区域3（传说之海）：500 → 100，由于单条鱼价值极高（4 星中位 850），
  更小的配额即可达到与区域2 相当的日产值，形成「高价值低频」的设计差异。

同时确保 fishing_cost 与配置中的区域费用保持一致。
"""

import sqlite3

from astrbot.api import logger

# 新配额：区域 id -> (每日稀有鱼配额, 钓鱼费用)
ZONE_SETTINGS = {
    1: (50, 10),
    2: (200, 60),
    3: (100, 110),
}


def up(cursor: sqlite3.Cursor):
    logger.info("正在执行 042_fix_zone_rare_fish_quota: 修正区域稀有鱼配额与钓鱼费用...")

    for zone_id, (quota, cost) in ZONE_SETTINGS.items():
        cursor.execute(
            """
            UPDATE fishing_zones
            SET daily_rare_fish_quota = ?, fishing_cost = ?
            WHERE id = ?
            """,
            (quota, cost, zone_id),
        )
        logger.info(f"  区域{zone_id}: 配额={quota}/天, 费用={cost}金币")

    # 新建区域（id > 3）使用默认费用，避免自建区域费用为 0
    cursor.execute(
        """
        UPDATE fishing_zones SET fishing_cost = 200
        WHERE id > 3 AND (fishing_cost IS NULL OR fishing_cost <= 0)
        """
    )

    logger.info("区域配额修正完成。")


def down(cursor: sqlite3.Cursor):
    logger.info("正在回滚 042_fix_zone_rare_fish_quota: 恢复原有配额...")

    # 恢复迁移 005 / 015 的原始设定
    original = {1: (50, 10), 2: (2000, 60), 3: (500, 110)}
    for zone_id, (quota, cost) in original.items():
        cursor.execute(
            "UPDATE fishing_zones SET daily_rare_fish_quota = ?, fishing_cost = ? WHERE id = ?",
            (quota, cost, zone_id),
        )

    logger.info("已恢复原有配额。")