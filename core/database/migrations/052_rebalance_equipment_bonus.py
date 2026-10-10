"""
迁移 052：重平衡装备加成曲线

（原编号 046，因与「新增救济区」迁移撞号导致互相跳过，重编号为 052 以修复冲突）

背景（审计发现）
----------------
量化四类装备属性的边际收益后发现严重失衡（以满配5 星鱼竿+ 5 星饰品计）：

| 属性 | 原效果 | 期望收益贡献 | 占比 |
|------|--------|-------------|------|
| rare_chance | 0.15 + 0.05 = 0.20 | 4.09× | ~90% |
| quantity_mod | ×1.1 × 1.1 = 1.21 | +21% | ~6% |
| quality_mod | ×1.2 × 1.2 = 1.44 | +4.6% | ~3% |
| coins_chance | ×1.25（幂指数修复后） | +6% | ~1% |

即 rare_chance 独占九成收益，其余三类加起来不足一成，
「品质加成」与「数量加成」沦为鸡肋属性，玩家没有动力购买非稀有向装备。

同时还修复了一个根本 BUG（见 migration 说明外的代码改动）：
``core/utils.get_fish_template`` 原用 ``base_value × (1 + coins_chance)``
给所有候选鱼乘同一常数，权重比例不变 → coins_chance 完全无效。
现改为幂指数加权 ``value ** (1 + coins_chance)``。

修正后的属性定位与目标占比
--------------------------
| 属性 | 定位 | 目标占比 |
|------|------|---------|
| rare_chance | 决定能否钓到高星鱼，装备核心价值 | ~45% |
| quantity_mod | 线性收益，玩家最易感知 | ~25% |
| quality_mod | 高品质鱼价值x2，惊喜感来源 | ~20% |
| coins_chance | 同稀有度内偏向高价值鱼 | ~10% |

具体调整
--------
1. **品质缩放系数** 0.175 → 0.5（新增配置 fishing.quality_chance_scale）
   满配品质 ×1.44 从 4.6% 提升到约 26% 的高品质概率。
2. **鱼竿数量曲线抬升**：4 星 1.05→1.20，5 星 1.10→1.30，
   使「买竿」有明确的数量收益，不再只卖 rare_chance。
3. **鱼竿品质小幅上调**：4 星 1.10→1.18，5 星 1.20→1.25。
4. **饰品金币加成上调**：渔夫戒指 1.25→1.30，海洋之心 1.25→1.35，
   让「金币向」饰品真正有区分度。
5. **饰品品质/数量同步上调**，与鱼竿形成互补。

兼容性：仅修改加成数值，不改变字段结构与接口，老数据可直接使用。
"""

import sqlite3

from astrbot.api import logger

# rod_id -> (quality_mod, quantity_mod, rare_mod)
ROD_UPDATES = {
    1: (1.00, 1.00, 0.00),   # 新手木竿（不变）
    2: (1.04, 1.05, 0.01),   # 竹制鱼竿
    3: (1.10, 1.12, 0.03),   # 碳素纤维竿
    4: (1.18, 1.20, 0.08),   # 星辰钓者
    5: (1.25, 1.30, 0.15),   # 海神之赐
}

# accessory_id -> (quality_mod, quantity_mod, rare_mod, coin_mod)
ACCESSORY_UPDATES = {
    1: (1.06, 1.00, 0.01, 1.05),  # 幸运四叶草
    2: (1.00, 1.00, 0.00, 1.30),  # 渔夫的戒指
    3: (1.12, 1.08, 0.03, 1.20),  # 丰收号角
    4: (1.22, 1.12, 0.05, 1.35),  # 海洋之心
}


def up(cursor: sqlite3.Cursor):
    logger.info("正在执行 052_rebalance_equipment_bonus: 重平衡装备加成曲线...")

    for rod_id, (q, qt, rc) in ROD_UPDATES.items():
        cursor.execute(
            """
            UPDATE rods
            SET bonus_fish_quality_modifier = ?,
                bonus_fish_quantity_modifier = ?,
                bonus_rare_fish_chance = ?
            WHERE rod_id = ?
            """,
            (q, qt, rc, rod_id),
        )
        logger.info(f"  鱼竿 {rod_id}: 品质×{q} 数量×{qt} 稀有+{rc * 100:.0f}%")

    for acc_id, (q, qt, rc, coin) in ACCESSORY_UPDATES.items():
        cursor.execute(
            """
            UPDATE accessories
            SET bonus_fish_quality_modifier = ?,
                bonus_fish_quantity_modifier = ?,
                bonus_rare_fish_chance = ?,
                bonus_coin_modifier = ?
            WHERE accessory_id = ?
            """,
            (q, qt, rc, coin, acc_id),
        )
        logger.info(
            f"  饰品 {acc_id}: 品质×{q} 数量×{qt} 稀有+{rc * 100:.0f}% 金币×{coin}"
        )

    logger.info("装备加成曲线重平衡完成——四类属性强度已趋于均衡。")


def down(cursor: sqlite3.Cursor):
    logger.info("正在回滚 052_rebalance_equipment_bonus...")

    rods_orig = {
        1: (1.00, 1.00, 0.00),
        2: (1.02, 1.00, 0.01),
        3: (1.05, 1.02, 0.03),
        4: (1.10, 1.05, 0.08),
        5: (1.20, 1.10, 0.15),
    }
    for rod_id, (q, qt, rc) in rods_orig.items():
        cursor.execute(
            """
            UPDATE rods SET bonus_fish_quality_modifier = ?,
                bonus_fish_quantity_modifier = ?, bonus_rare_fish_chance = ?
            WHERE rod_id = ?
            """,
            (q, qt, rc, rod_id),
        )

    acc_orig = {
        1: (1.05, 1.00, 0.01, 1.02),
        2: (1.00, 1.00, 0.00, 1.25),
        3: (1.10, 1.05, 0.03, 1.15),
        4: (1.20, 1.10, 0.05, 1.25),
    }
    for acc_id, (q, qt, rc, coin) in acc_orig.items():
        cursor.execute(
            """
            UPDATE accessories SET bonus_fish_quality_modifier = ?,
                bonus_fish_quantity_modifier = ?, bonus_rare_fish_chance = ?,
                bonus_coin_modifier = ?
            WHERE accessory_id = ?
            """,
            (q, qt, rc, coin, acc_id),
        )

    logger.info("已恢复原装备加成数值。")