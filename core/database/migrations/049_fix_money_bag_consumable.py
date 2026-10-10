"""
迁移 049：修正钱袋类道具的 is_consumable 标记。

背景
----
钱袋（effect_type = 'ADD_COINS'）应通过「开启全部钱袋」(/开启全部钱袋) 或「使用」开启获得金币，
而 inventory_service.open_all_money_bags 的过滤条件同时要求
`effect_type == 'ADD_COINS' AND is_consumable == True`。

数据初值存在不一致：中号/大号/神秘/巨型钱袋的 is_consumable 均为 1，
唯独「小钱袋」（每日补给池卡池3 白给的小钱袋×2，是最常见的金币来源）被写成 0。
结果是：玩家从抽卡领取到的小钱袋无法被开启，gacha-only 的金币来源形同虚设。

本迁移将所有 ADD_COINS 且 is_consumable=0 的钱袋统一置为 1（与同类道具保持一致），
确保抽到的钱袋可正常开启。initial_data.py 中「小钱袋」的初值也已改为 True，
新库在 seed 阶段即正确；本迁移只负责修正已落库的旧数据。

up  : UPDATE items SET is_consumable=1 WHERE effect_type='ADD_COINS' AND is_consumable=0
down: 仅回退「小钱袋」的标记（恢复迁移前初值 0）
"""

from astrbot.api import logger


def up(cursor):
    logger.info("正在执行 049_fix_money_bag_consumable: 修正钱袋 is_consumable 标记...")

    cursor.execute(
        """
        UPDATE items
        SET is_consumable = 1
        WHERE effect_type = 'ADD_COINS' AND is_consumable = 0
        """
    )
    updated = cursor.rowcount
    logger.info(f"049_fix_money_bag_consumable: 已修正 {updated} 个钱袋道具的 is_consumable 标记")


def down(cursor):
    logger.info("正在回滚 049_fix_money_bag_consumable: 恢复小钱袋 is_consumable=0...")

    cursor.execute(
        """
        UPDATE items
        SET is_consumable = 0
        WHERE effect_type = 'ADD_COINS' AND name = '小钱袋'
        """
    )
    logger.info("049_fix_money_bag_consumable 回滚完成：小钱袋 is_consumable 已恢复为 0")
