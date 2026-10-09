"""
迁移 043：启用区域通行证机制，激活「前往神秘海域的通行证」

背景
----
道具「前往神秘海域的通行证」(item_id=5) 的完整机制早已实现
（fishing_service.py 中 requires_pass / required_item_id / 每日检查任务），
但迁移 015 创建的三个区域全部 requires_pass=0，
导致该道具永远不会被消耗 —— 一个完全无法使用的死道具。

本次处理
--------
1. **新建区域4「无尽深渊」**：需要通行证才能进入。
   这让通行证有唯一且清晰的消耗出口，同时给高星玩家一个长期追求的目标。
   该区域定位为「顶级玩家的专属猎场」，单次费用高、稀有鱼配额严格。

2. 若该区域已存在则跳过创建（迁移可重复执行）。

区域4 数值设计
--------------
- 钓鱼费用 500 金币：约为区域3（110）的 4.5 倍，对应更高的期望收益。
- 稀有鱼配额 30/天：比区域3（100）更严格，但单条价值远高，
  形成「高门槛 / 高价值 / 强稀缺」的设计，与区域3 的「低门槛 / 中频」区分开。
- 稀有度分布：集中在 5-6 星，7-8 星有极低概率，配合 required_item_id 做长线目标。
"""

import sqlite3
from datetime import datetime

from astrbot.api import logger

ZONE_ID = 4
ZONE_NAME = "无尽深渊"
ZONE_DESC = "传说中通往深渊的裂口，只有持通行证者得以窥见。"

# 需要通关证的道具 id：5 = 前往神秘海域的通行证
PASS_ITEM_ID = 5
FISHING_COST = 500
DAILY_QUOTA = 30

# 稀有度分布：[1星, 2星, 3星, 4星, 5星, 6星及以上的暂定占比]
# 说明：数组会在 fishing_zone_service 中补齐到 6 位。
RARITY_DISTRIBUTION = [0.05, 0.10, 0.20, 0.25, 0.25, 0.15]


def up(cursor: sqlite3.Cursor):
    logger.info("正在执行 043_enable_zone_pass: 启用区域通行证机制...")

    # 检查该区域是否已存在
    cursor.execute("SELECT id, requires_pass FROM fishing_zones WHERE id = ?", (ZONE_ID,))
    existing = cursor.fetchone()

    if existing:
        # 已存在则仅更新关键字段，避免覆盖管理员在后台做的其他调整
        cursor.execute(
            """
            UPDATE fishing_zones
            SET requires_pass = 1,
                required_item_id = ?,
                fishing_cost = ?,
                is_active = 1
            WHERE id = ?
            """,
            (PASS_ITEM_ID, FISHING_COST, ZONE_ID),
        )
        logger.info(f"  区域{ZONE_ID} 已存在，已更新其通行证要求。")
    else:
        # fishing_zones.configs 为 JSON 字符串，存放稀有度分布
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
            VALUES (?, ?, ?, ?, 0, ?, 1, NULL, NULL, ?, 1, ?)
            """,
            (
                ZONE_ID,
                ZONE_NAME,
                ZONE_DESC,
                DAILY_QUOTA,
                configs,
                PASS_ITEM_ID,
                FISHING_COST,
            ),
        )
        logger.info(
            f"  已创建区域{ZONE_ID}「{ZONE_NAME}」："
            f"需要通行证(道具{PASS_ITEM_ID})、费用{FISHING_COST}金币、配额{DAILY_QUOTA}/天"
        )

    logger.info("区域通行证机制启用完成——「前往神秘海域的通行证」已有明确用途。")


def down(cursor: sqlite3.Cursor):
    logger.info("正在回滚 043_enable_zone_pass...")
    try:
        # 只解除通行证要求，保留区域本体（删除区域会导致玩家数据丢失）
        cursor.execute(
            "UPDATE fishing_zones SET requires_pass = 0, required_item_id = NULL WHERE id = ?",
            (ZONE_ID,),
        )
        logger.info(f"区域{ZONE_ID} 的通行证要求已解除（区域本体保留）。")
    except Exception as e:
        logger.error(f"回滚 043 失败: {e}")
        raise