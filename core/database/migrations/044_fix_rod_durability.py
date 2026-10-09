"""
迁移 044：修正鱼竿耐久曲线

背景
----
原 ROD_DATA 中只有 3 星「碳素纤维竿」设了耐久 1000，而 1/2 星竿与
4/5 星竿（星石购买、最贵）的耐久均为 None（无限）。

这造成明显的体验倒挂：玩家花钱升级到 3 星竿后开始「越用越亏」，
而继续升级到 4/5 星反而又变成无限耐久。耐久本应提供回收节奏，
不该惩罚做出正确升级决策的玩家。

修正为递增梯度（新手竿不设耐久，保护初期体验）
-----------------------------------------------
| 鱼竿| 星级 | 价格 | 原耐久 | 新耐久 | 约可用时长(CD=180s) |
|------|------|------------|--------|--------|-------------------|
| 新手木竿 | 1 | 50 金币 | ∞ | ∞ | 不损耗 |
| 竹制鱼竿 | 2 | 500 金币 | ∞ | 500 | ≈ 41 小时 |
| 碳素纤维竿 | 3 | 5000 金币 | 1000 | 2000 | ≈ 166 小时 |
| 星辰钓者 | 4 | 300 星石 | ∞ | 8000 | ≈ 666 小时 |
| 海神之赐 | 5 | 900 星石 | ∞ | 30000 | ≈ 2500 小时 |

原则：**单次可用时长随星级递增**，让高星竿虽有损耗但始终优于低星竿。
"""

import sqlite3

from astrbot.api import logger

# fish_id -> 新耐久值
ROD_DURABILITY = {
    1: None,   # 新手木竿：保持无限
    2: 500,    # 竹制鱼竿
    3: 2000,   # 碳素纤维竿
    4: 8000,   # 星辰钓者
    5: 30000,  # 海神之赐
}


def up(cursor: sqlite3.Cursor):
    logger.info("正在执行 044_fix_rod_durability: 修正鱼竿耐久曲线...")

    for rod_id, durability in ROD_DURABILITY.items():
        cursor.execute(
            """
            UPDATE rods
            SET durability = ?
            WHERE rod_id = ?
            """,
            (durability, rod_id),
        )
        desc = "无限" if durability is None else f"{durability} 次"
        logger.info(f"  鱼竿ID {rod_id}: 耐久 -> {desc}")

    # 同步更新玩家已持有的鱼竿实例的耐久上限。
    # 注意：只上调「当前耐久超过新上限」的实例，避免已有装备被意外削弱；
    # 当前耐久低于新上限的原样保留（说明玩家已经消耗过一部分）。
    for rod_id, durability in ROD_DURABILITY.items():
        if durability is None:
            continue
        cursor.execute(
            """
            UPDATE user_rods
            SET current_durability = ?
            WHERE rod_id = ?
              AND current_durability IS NOT NULL
              AND current_durability > ?
            """,
            (durability, rod_id, durability),
        )
        updated = cursor.rowcount
        if updated > 0:
            logger.info(f"  已同步 {updated} 个 {rod_id} 号鱼竿实例的耐久上限至 {durability}")

    logger.info("鱼竿耐久曲线修正完成——单次可用时长现随星级递增。")


def down(cursor: sqlite3.Cursor):
    logger.info("正在回滚 044_fix_rod_durability: 恢复原耐久...")

    original = {
        1: None,
        2: None,
        3: 1000,
        4: None,
        5: None,
    }
    for rod_id, durability in original.items():
        cursor.execute(
            "UPDATE rods SET durability = ? WHERE rod_id = ?",
            (durability, rod_id),
        )
    logger.info("已恢复原耐久设定。")