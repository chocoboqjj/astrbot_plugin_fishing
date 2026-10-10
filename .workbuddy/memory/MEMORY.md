# astrbot_plugin_fishing 项目长期约定

## 提交规范（用户明确要求）
- **每次提交都必须同步更新 `README.md`**，使文档与实际功能/配置保持一致。
  （用户原话：「每次提交readme也记得更新」）
- 提交前应确认：README 已反映本轮改动的玩法、配置、命令与依赖变化。
- 版本号遵循 `metadata.yaml` / `README.md` / `CHANGELOG.md` 三处同步（当前 2.4.7）。

## 排障备忘
- **`fish.db` 残留是「用户已注册」类问题的第一嫌疑**。用户重置环境时若没删干净 `fish.db`，
  旧账号会残留，注册即提示「用户已注册」（2026-10-10 用户亲历，原因就是 fish.db 没删干净）。
- 重置环境正确姿势：停插件 → 删除 `fish.db`（路径来自 `context.get_data_dir("astrbot_plugin_fishing")`，
  在插件目录之外，重装/重载插件都不会清它）→ 重启。
- 账号 **全局不按群隔离**：`user_id = event.get_sender_id()`（main.py `_get_effective_user_id`），
  同一平台任意群/私聊注册过则处处提示已注册。玩家侧无「注销」命令，删号只能走 Web 后台
  （`user_service.delete_user_for_admin`）。
- `MARKET` 是系统虚拟用户（market_service 自动创建，用于托管上架装备），出现在 users 表属正常。

## 项目结构要点
- 配置单一事实来源：`core/config_defaults.py`（`build_game_config()` 做容错与区间修正）
- 配置流：`_conf_schema.json → AstrBotConfig → build_game_config → 各 Service`
- **AstrBot Schema 铁律**：`type: "object"` 节点必须带 `items`，否则框架 `node["items"]` 抛 `KeyError`，
  插件直接加载失败（曾因 12 处违规导致安装报错）。改 schema 后必须跑一次模拟解析验证。
- 迁移脚本：`core/database/migrations/NNN_*.py`，由 `migration.py` **按文件路径**动态加载
  （早期用硬编码包路径 `data.plugins...` 会 ModuleNotFoundError，已修）。
  迁移中每个用到 `logger` 的函数都要**各自** `from astrbot.api import logger`（`up()` 有不代表 `down()` 有）。
- **⚠️ 迁移版本号铁律（2026-10-10 踩坑）**：迁移文件名前缀 `NNN` **必须全局唯一**，新增迁移编号 = 当前最大编号 + 1。
  `migration.py` 只执行 `version > current_version` 的迁移，且 `up()` 会把 `schema_version` 设成该迁移的版本号。
  **两个迁移撞同一版本号 → 先跑的把版本顶上去，另一个（及同版本兄弟）被永久跳过**，表现为「代码写了但库里没数据」。
  本次 `046_add_relief_zone`(建区域5) 与 `046_rebalance_equipment_bonus`(装备重平衡) 撞号 46，导致区域5 从未入库
  （用户反馈「区域五没生效」）。已重编号为 052 / 053 修复。**新增迁移前务必 `ls core/database/migrations` 核对最大编号。**
- 命令帮助图在 `draw/help.py`，改玩法/命令后必须同步（曾 11 轮未同步）。
- 成就走 Python 类定义（`core/achievements/`）+ `user_achievement_progress` 表，无 `achievements` 表。

## 已知设计遗留（勿踩坑）
- `game_config["zones"]` **只生产、零消费**：区域费用/配额真实来源是 `fishing_zones` 表
  （迁移 042 配额 / 045 费用+星级分布）。改 `DEFAULT_ZONE_CONFIG` 不会生效。
- `runtime_config` 表（迁移 041）已成孤儿：访问层已删，表仍在建。
- 区域星级分布固定 6 段（1★~6+★），缺第 6 段会导致 6 星鱼不可达。

## 测试/验证手法
- AstrBot 桩模块 + 临时 SQLite：可完整构造 `FishingPlugin`（注意需在 `asyncio.run` 内，
  `__init__` 会 `asyncio.create_task`）。
- 依赖装在 `/Users/adelenaumann/.workbuddy/binaries/python/envs/default`（含 pyflakes）。
- 数值改动用蒙特卡洛验证（区域1 钓 1000 次，成功率期望 0.700）。
