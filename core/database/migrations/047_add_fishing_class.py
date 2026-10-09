import sqlite3

# ==========================================================
# 迁移 047：钓鱼阶级系统（段位制 · 纯增益型）
# ==========================================================
# 设计要点
# --------
# 1. 阶级为「段位制」：单一纵向阶梯，按双门槛自动晋升、只升不降。
# 2. 双门槛 = 累计钓鱼次数 + 图鉴收集数。
#    只用次数会让自动钓鱼挂机即可满阶；加入图鉴门槛后，
#    高阶真正被「收集深度」卡住（112 种鱼里的 6★ 稀有鱼极难出）。
# 3. 特权为「纯增益型」：仅提供税收折扣 / 商店折扣 / 称号，
#    **不锁定任何已有内容**（区域、鱼塘档位、精炼等级均不受影响），
#    因此老玩家不会被反向卡住。
# 4. 本迁移会按现有数据回填阶级，老玩家直接获得应得阶级，不掉档。
#
# ⚠️ 门槛数值与 core/config_defaults.py 的 DEFAULT_FISHING_CLASS_CONFIG 保持一致；
#    迁移必须能独立运行，因此此处不导入配置模块，而是内联一份同样的默认值。

# (level, name, 钓鱼次数门槛, 图鉴门槛, title_id)
CLASS_TIERS = [
    (1, "见习钓手", 0, 0, 901),
    (2, "初阶钓手", 50, 5, 902),
    (3, "熟练钓手", 200, 15, 903),
    (4, "资深钓手", 500, 28, 904),
    (5, "钓鱼高手", 1200, 42, 905),
    (6, "钓鱼大师", 2500, 58, 906),
    (7, "钓鱼宗师", 5000, 74, 907),
    (8, "传说钓者", 9000, 90, 908),
    (9, "钓神", 15000, 102, 909),
]

# 图鉴总数，用于展示进度（与 initial_data.FISH_DATA 数量一致）
TOTAL_FISH_SPECIES = 112


def _title_name(level_name: str) -> str:
    """阶级称号名（与阶级同名，便于玩家理解）"""
    return level_name


def _calc_level(fish_count: int, pokedex: int) -> int:
    """按双门槛计算阶级：两项需同时满足"""
    level = 1
    for lv, _name, need_count, need_pokedex, _tid in CLASS_TIERS:
        if fish_count >= need_count and pokedex >= need_pokedex:
            level = lv
    return level


def up(cursor: sqlite3.Cursor):
    from astrbot.api import logger
    logger.info("正在执行 047_add_fishing_class: 新增钓鱼阶级系统...")

    # 1. users 表新增阶级字段
    existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(users)")}
    if "fishing_class_level" not in existing_cols:
        cursor.execute(
            "ALTER TABLE users ADD COLUMN fishing_class_level INTEGER NOT NULL DEFAULT 1"
        )
    if "fishing_class_score" not in existing_cols:
        cursor.execute(
            "ALTER TABLE users ADD COLUMN fishing_class_score INTEGER NOT NULL DEFAULT 0"
        )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_class_level ON users(fishing_class_level)"
    )

    # 2. 播种阶级称号（ID 901-909，避开现有称号 ID 段）
    for lv, name, need_count, need_pokedex, title_id in CLASS_TIERS:
        desc = f"钓鱼阶级达到「{name}」（累计钓鱼 {need_count} 次且图鉴收集 {need_pokedex} 种）"
        cursor.execute(
            "INSERT OR IGNORE INTO titles (title_id, name, description, display_format) "
            "VALUES (?, ?, ?, ?)",
            (title_id, _title_name(name), desc, "{name}"),
        )

    # 3. 回填：按现有钓鱼次数 + 图鉴数计算阶级，并补发对应称号
    rows = cursor.execute(
        """
        SELECT u.user_id, u.total_fishing_count,
               (SELECT COUNT(*) FROM user_fish_stats s WHERE s.user_id = u.user_id) AS pokedex
        FROM users u
        """
    ).fetchall()

    title_by_level = {lv: tid for lv, _n, _c, _p, tid in CLASS_TIERS}
    promoted = 0
    for user_id, fish_count, pokedex in rows:
        fish_count = fish_count or 0
        pokedex = pokedex or 0
        level = _calc_level(fish_count, pokedex)
        # 钓力值（展示用）：次数 + 图鉴×20，仅用于排行与展示，不作为门槛
        score = fish_count + pokedex * 20
        cursor.execute(
            "UPDATE users SET fishing_class_level = ?, fishing_class_score = ? WHERE user_id = ?",
            (level, score, user_id),
        )
        # 补发该阶级及以下所有阶级称号，避免老玩家缺中间档称号
        for lv in range(1, level + 1):
            cursor.execute(
                "INSERT OR IGNORE INTO user_titles (user_id, title_id) VALUES (?, ?)",
                (user_id, title_by_level[lv]),
            )
        if level > 1:
            promoted += 1

    logger.info(
        f"047_add_fishing_class: 已回填 {len(rows)} 名用户的阶级（{promoted} 人达到 2 阶及以上）"
    )


def down(cursor: sqlite3.Cursor):
    from astrbot.api import logger
    logger.info("正在回滚 047_add_fishing_class: 移除钓鱼阶级系统...")

    # 移除用户已获得的阶级称号
    for _lv, _name, _c, _p, title_id in CLASS_TIERS:
        cursor.execute("DELETE FROM user_titles WHERE title_id = ?", (title_id,))
        cursor.execute("DELETE FROM titles WHERE title_id = ?", (title_id,))

    cursor.execute("DROP INDEX IF EXISTS idx_users_class_level")

    existing_cols = {row[1] for row in cursor.execute("PRAGMA table_info(users)")}
    if "fishing_class_score" in existing_cols:
        cursor.execute("ALTER TABLE users DROP COLUMN fishing_class_score")
    if "fishing_class_level" in existing_cols:
        cursor.execute("ALTER TABLE users DROP COLUMN fishing_class_level")

    logger.info("047_add_fishing_class 回滚完成")
