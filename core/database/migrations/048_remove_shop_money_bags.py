"""
迁移 048：移除商店中「可购买的钱袋」商品。

背景
----
店3（黑潮交易所）原本出售 小/中/神秘/大/巨型钱袋 与 囤货箱，售价约为面值的 4~6 倍，
定位是「花金币买便利 + 回收超发金币」的 gold sink。但玩家容易误以为这是「买金币」的出口，
且确定性购买与「钱袋应靠抽取获得」的设计取向冲突。

本迁移删除店3 中所有 `category = 'money'` 的商品（即上述 6 个钱袋类条目），
其关联的成本/奖励由 `shop_item_costs` / `shop_item_rewards` 的 ON DELETE CASCADE 一并清理。

钱袋的获取改为仅限抽卡（每日补给池白给 小钱袋×2），不再出现在确定性商店中。

up  : 删除店3 的钱包类商品
down: 重新插入这 6 个商品（含成本与奖励），恢复到迁移前的状态
注意：down() 必须在 initial_data.py 的 ITEM_DATA 已落库（item_id 稳定）之后执行。
"""

from astrbot.api import logger

# 与 initial_data.py 店3 原条目保持一致，用于 down() 复原
_SHOP3_MONEY_BAGS = [
    # (name, description, sort_order, per_user_daily_limit, cost_coins, [(reward_type, reward_item_id, qty), ...])
    ("小钱袋", "一个装有少量金币的袋子。面值 1000", 101, 5, 5000,
     [("item", 1, 1)]),
    ("中号钱袋", "一个沉甸甸的钱袋。面值 10000", 102, 3, 40000,
     [("item", 7, 1)]),
    ("神秘钱袋", "会变换重量的神秘钱袋，随机获得 5000~20000 金币", 103, 3, 60000,
     [("item", 9, 1)]),
    ("大号钱袋", "一个鼓鼓囊囊的大钱袋。面值 50000", 104, 2, 180000,
     [("item", 8, 1)]),
    ("巨型钱袋", "仿佛装满了全世界财富的巨大袋子，随机获得 10万~50万 金币", 105, 1, 1200000,
     [("item", 10, 1)]),
    ("囤货箱", "一次性购入多只钱袋，适合中后期囤积金币。限购 2 次", 201, 2, 1500000,
     [("item", 8, 2), ("item", 9, 2)]),
]


def up(cursor):
    logger.info("正在执行 048_remove_shop_money_bags: 移除店3可购买的钱袋商品...")

    cursor.execute(
        "DELETE FROM shop_items WHERE shop_id = 3 AND category = 'money'"
    )
    deleted = cursor.rowcount
    logger.info(f"048_remove_shop_money_bags: 已删除店3 钱袋类商品 {deleted} 个（成本/奖励随级联删除清理）")


def down(cursor):
    logger.info("正在回滚 048_remove_shop_money_bags: 重新插入店3钱袋商品...")

    for (name, desc, sort_order, daily_limit, cost, rewards) in _SHOP3_MONEY_BAGS:
        cursor.execute(
            """
            INSERT INTO shop_items
                (shop_id, name, description, category, is_active, sort_order, per_user_daily_limit)
            VALUES (3, ?, ?, 'money', 1, ?, ?)
            """,
            (name, desc, sort_order, daily_limit),
        )
        item_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO shop_item_costs (item_id, cost_type, cost_amount, cost_relation) VALUES (?, 'coins', ?, 'and')",
            (item_id, cost),
        )
        for (rtype, rid, qty) in rewards:
            cursor.execute(
                "INSERT INTO shop_item_rewards (item_id, reward_type, reward_item_id, reward_quantity) VALUES (?, ?, ?, ?)",
                (item_id, rtype, rid, qty),
            )

    logger.info("048_remove_shop_money_bags 回滚完成：已恢复 6 个店3钱袋商品")
