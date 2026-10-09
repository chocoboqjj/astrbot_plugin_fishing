# astrbot_plugin_fishing 项目长期约定

## 提交规范（用户明确要求）
- **每次提交都必须同步更新 `README.md`**，使文档与实际功能/配置保持一致。
  （用户原话：「每次提交readme也记得更新」）
- 提交前应确认：README 已反映本轮改动的玩法、配置、命令与依赖变化。
- 版本号遵循 `metadata.yaml` / `README.md` / `CHANGELOG.md` 三处同步（当前 2.4.7）。

## 项目结构要点
- 配置单一事实来源：`core/config_defaults.py`（`build_game_config()` 做容错与区间修正）
- 配置流：`_conf_schema.json → AstrBotConfig → build_game_config → 各 Service`
- **AstrBot Schema 铁律**：`type: "object"` 节点必须带 `items`，否则框架 `node["items"]` 抛 `KeyError`，
  插件直接加载失败（曾因 12 处违规导致安装报错）。改 schema 后必须跑一次模拟解析验证。
- 迁移脚本：`core/database/migrations/NNN_*.py`，由 `migration.py` **按文件路径**动态加载
  （早期用硬编码包路径 `data.plugins...` 会 ModuleNotFoundError，已修）。
  迁移中每个用到 `logger` 的函数都要**各自** `from astrbot.api import logger`（`up()` 有不代表 `down()` 有）。
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
