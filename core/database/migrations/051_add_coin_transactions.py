"""
迁移 051：新增「金币交易流水」表 coin_transactions

背景
----
此前所有金币增减（商店购买、卖出装备、钓鱼卖鱼、抽卡、税收等）都只直接改写
``users.coins``，**不记录任何来源可追溯的流水**。这导致：
- 玩家通过「低买高卖」商店装备刷金币（如新手木竿 买50 卖100）时，
  系统无法区分「刷出来的金币」与「正常游玩所得」，事后既无法精准定位刷子，
  也无法按来源追回。
- 本次买卖刷钱漏洞（见未发布章节「防刷钱：商店装备回购价封顶」）即因此无法追溯。

设计
----
新增 coin_transactions 表，记录每一笔与「装备买卖」相关的金币流入/流出，
字段足以支撑未来的精准追回查询：
- user_id / tx_type（shop_buy | sell_rod | sell_accessory | sell_all_rods |
  sell_all_accessories | sell_everything）
- item_type（rod | accessory，便于按装备类型聚合）
- item_id（rod/accessory 模板 id，是锁定「买 rod_id=1 再卖」套利回路的关键）
- rarity / quantity / coins_delta（正=收入 负=支出）
- balance_after（操作后余额快照，便于审计）
- created_at（UTC，定位时间窗）

注意
----
1. 本迁移只建表 + 索引，不回填历史（历史无日志，无法回溯）。
2. 写入点在 ShopService.purchase_item（买装备花金币）与 InventoryService 各卖出路径
   （卖装备得金币），均带 item_id/rarity，使「某用户买/卖 rod_id=1 的次数与金额」
   可被一条 SQL 汇总出来。
3. 流水写入做了异常隔离：日志失败只告警，不影响主交易（购买/卖出照常成功）。
"""

import sqlite3

from astrbot.api import logger


def up(cursor: sqlite3.Cursor):
    logger.info("正在执行 051_add_coin_transactions: 新增金币交易流水表...")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS coin_transactions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      TEXT    NOT NULL,
            tx_type      TEXT    NOT NULL,
            item_type    TEXT,
            item_id      INTEGER,
            rarity       INTEGER,
            quantity     INTEGER NOT NULL DEFAULT 1,
            coins_delta  INTEGER NOT NULL,
            balance_after INTEGER,
            created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_coin_tx_user ON coin_transactions(user_id)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_coin_tx_user_type ON coin_transactions(user_id, tx_type)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_coin_tx_user_item "
        "ON coin_transactions(user_id, tx_type, item_id)"
    )
    logger.info("已创建 coin_transactions 表及索引——装备买卖流水现在可溯源。")


def down(cursor: sqlite3.Cursor):
    logger.info("正在回滚 051_add_coin_transactions...")
    try:
        cursor.execute("DROP TABLE IF EXISTS coin_transactions")
        logger.info("coin_transactions 表已删除。")
    except Exception as e:
        logger.error(f"回滚 051 失败: {e}")
        raise
