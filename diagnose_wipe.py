#!/usr/bin/env python3
# 一次性诊断：核查某用户的「今日擦弹已用次数」到底是怎么算出来的。
# 用法：python diagnose_wipe.py <fish.db 路径> [user_id(可选，不填则列出全部)]
import sys, json, sqlite3
from datetime import datetime, timedelta, timezone

UTC8 = timezone(timedelta(hours=8))
db = sys.argv[1]
uid = sys.argv[2] if len(sys.argv) > 2 else None

conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 复刻插件里的“今日”口径（UTC+8）
today_start = datetime.now(UTC8).replace(hour=0, minute=0, second=0, microsecond=0)
today_end = today_start + timedelta(days=1)

# 1) 每张表的列，确认存在
def cols(t):
    cur.execute(f"PRAGMA table_info({t})")
    return {r["name"] for r in cur.fetchall()}

has_log = "wipe_bomb_log" in {r["name"] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
print(f"数据库: {db}")
print(f"今日(UTC+8)区间: {today_start}  ~  {today_end}\n")

if has_log:
    # 今日 wipe_bomb_log 真实行数（按用户）
    q = """SELECT user_id, COUNT(*) c FROM wipe_bomb_log
           WHERE timestamp >= ? AND timestamp < ? AND contribution_amount > 0
           GROUP BY user_id ORDER BY c DESC"""
    cur.execute(q, (today_start, today_end))
    rows = cur.fetchall()
    print("== 今日 wipe_bomb_log 行数（插件回执用的 used）==")
    for r in rows:
        print(f"  user={r['user_id']}  今日日志数={r['c']}")
    if not rows:
        print("  （无）")

    # 逐条列出今日擦弹日志（含时间戳），用于确认“已用”是否为真实 4 次
    print("\n== 今日擦弹日志明细（按时间升序，贡献额>0）==")
    detail = """SELECT user_id, timestamp, contribution_amount, reward_multiplier
                FROM wipe_bomb_log
                WHERE timestamp >= ? AND timestamp < ? AND contribution_amount > 0
                ORDER BY timestamp ASC"""
    cur.execute(detail, (today_start, today_end))
    drows = cur.fetchall()
    if not drows:
        print("  （无）")
    else:
        for i, r in enumerate(drows, 1):
            print(f"  #{i}  user={r['user_id']}  time={r['timestamp']}  "
                  f"投入={r['contribution_amount']}  倍率={r['reward_multiplier']}")

# 2) users 表里的 wipe_bomb_attempts_today / last_wipe_bomb_date
uc = cols("users")
if "wipe_bomb_attempts_today" in uc:
    print("\n== users 表（/擦弹 执行与状态图用的 used）==")
    sql = "SELECT user_id, wipe_bomb_attempts_today, last_wipe_bomb_date FROM users"
    if uid:
        sql += " WHERE user_id=?"
        cur.execute(sql, (uid,))
    else:
        cur.execute(sql)
    for r in cur.fetchall():
        print(f"  user={r['user_id']}  attempts_today={r['wipe_bomb_attempts_today']}  last_date={r['last_wipe_bomb_date']}")

# 3) 当前 WIPE_BOMB_ATTEMPTS_BOOST buff 存量
bc = cols("user_buffs")
if "buff_type" in bc:
    print("\n== 当前擦弹加成 buff（决定上限里 extra 多少）==")
    sql = "SELECT user_id, payload, expires_at FROM user_buffs WHERE buff_type='WIPE_BOMB_ATTEMPTS_BOOST'"
    if uid:
        sql += " AND user_id=?"
        cur.execute(sql, (uid,))
    else:
        cur.execute(sql)
    for r in cur.fetchall():
        try:
            amt = json.loads(r["payload"]).get("amount")
        except Exception:
            amt = "?"
        print(f"  user={r['user_id']}  buff.amount={amt}  expires={r['expires_at']}")

# 4) 基础每日上限（默认 3，实际以 game_config 为准）
print("\n解读：")
print("  插件回执的「已用」= 上面『今日 wipe_bomb_log 行数』。")
print("  若它 == 你今天真实 /擦弹 次数 → 数字无误，剩余=(基础3+buff) - 已用。")
print("  若它明显大于你真实次数 → used 被夸大（时区/跨天口径问题），需修计数逻辑。")
