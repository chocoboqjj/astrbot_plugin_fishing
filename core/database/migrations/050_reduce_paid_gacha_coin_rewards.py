"""
迁移 050：下调付费卡池的金币产出，使付费抽卡由「净印钞」转为「净消耗」。

背景
----
经济模型审计（2026-10）发现：付费卡池（池1 稀有鱼竿池 / 池2 珍贵饰品池）的
金币奖励远高于抽卡成本，形成持续的金币水龙头（通胀源）：
  · 池1：成本 5000，金币奖励 10000（权重 57%）→ 单抽期望硬币 ≈ +5700
  · 池2：成本 10000，金币奖励 20000（权重 80%）→ 单抽期望硬币 ≈ +16000

玩家可反复投入金币抽卡、抽到的金币又回流，金币总量只增不减，
与「移除可购买钱袋（迁移 048/049）」的治理方向背道而驰。

本迁移将付费池金币奖励下调，使单抽期望变为净消耗：
  · 池1：10000 → 3000（权重 57%）→ 单抽期望硬币 ≈ -1710
  · 池2：20000 → 5000（权重 80%）→ 单抽期望硬币 ≈ -2100

免费池（池3）不受影响，仍作为普通玩家的日常金币来源。
initial_data.py 中 GACHA_POOL_ITEMS 的初值已同步下调，新库在 seed 阶段即正确；
由于 gacha_pool_items 按池幂等（已有物品的池子跳过 seed），本迁移只负责
修正已落库的旧数据。

up  : 池1/池2 的 coins 物品 quantity 分别改为 3000 / 5000
down: 仅回退池1/池2 金币数量为迁移前初值（10000 / 20000）
"""

from astrbot.api import logger


def up(cursor):
    logger.info("正在执行 050_reduce_paid_gacha_coin_rewards: 下调付费卡池金币产出...")

    cursor.execute(
        """
        UPDATE gacha_pool_items
        SET quantity = 3000
        WHERE gacha_pool_id = 1 AND item_type = 'coins' AND item_id = '0'
        """
    )
    p1 = cursor.rowcount

    cursor.execute(
        """
        UPDATE gacha_pool_items
        SET quantity = 5000
        WHERE gacha_pool_id = 2 AND item_type = 'coins' AND item_id = '0'
        """
    )
    p2 = cursor.rowcount

    logger.info(
        f"050_reduce_paid_gacha_coin_rewards: 池1 修正 {p1} 行，池2 修正 {p2} 行"
    )


def down(cursor):
    logger.info("正在回滚 050_reduce_paid_gacha_coin_rewards: 恢复付费卡池金币初值...")

    cursor.execute(
        """
        UPDATE gacha_pool_items
        SET quantity = 10000
        WHERE gacha_pool_id = 1 AND item_type = 'coins' AND item_id = '0'
        """
    )
    cursor.execute(
        """
        UPDATE gacha_pool_items
        SET quantity = 20000
        WHERE gacha_pool_id = 2 AND item_type = 'coins' AND item_id = '0'
        """
    )

    logger.info("050_reduce_paid_gacha_coin_rewards 回滚完成")
