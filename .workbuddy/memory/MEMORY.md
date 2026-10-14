# astrbot_plugin_fishing 项目长期约定

## 提交规范（用户明确要求）
- **每次提交都必须同步更新 `README.md`**，使文档与实际功能/配置保持一致。
  （用户原话：「每次提交readme也记得更新」）
- 提交前应确认：README 已反映本轮改动的玩法、配置、命令与依赖变化。
- 版本号遵循 `metadata.yaml` / `README.md` / `CHANGELOG.md` 三处同步（当前 2.4.9）。

## 排障备忘
- **`fish.db` 残留是「用户已注册」类问题的第一嫌疑**。用户重置环境时若没删干净 `fish.db`，
  旧账号会残留，注册即提示「用户已注册」（2026-10-10 用户亲历，原因就是 fish.db 没删干净）。
- 重置环境正确姿势：停插件 → 删除 `fish.db`（路径来自 `context.get_data_dir("astrbot_plugin_fishing")`，
  在插件目录之外，重装/重载插件都不会清它）→ 重启。
- 账号 **全局不按群隔离**：`user_id = event.get_sender_id()`（main.py `_get_effective_user_id`），
  同一平台任意群/私聊注册过则处处提示已注册。玩家侧无「注销」命令，删号只能走 Web 后台
  （`user_service.delete_user_for_admin`）。
- `MARKET` 是系统虚拟用户（market_service 自动创建，用于托管上架装备），出现在 users 表属正常。
- **⚠️ 平台切换账号不兼容（2026-10-13 踩坑）**：NapCat(aiocqhttp) 下 `get_sender_id()` 返回纯数字 QQ 号；
  QQ 官方 Bot(qq_official) 下返回 **openid**（字母数字串，如 `nhB9vRr...`），二者格式不同且**无映射**，
  旧 `fish.db`（存 QQ 号）在官方 Bot 下全部查不到 → 玩家显示「未注册」。切官方 Bot 需清空 `fish.db` 重注册。
- **QQ 官方 Bot 接入方式（框架层，非插件代码）**：AstrBot 面板 → 机器人 → +创建 → QQ 官方机器人(WebSocket)
  → 填 appid/secret → **务必勾 `enable_group_c2c`**（否则收不到群消息）→ QQ开放平台加 IP 白名单。
- **@人解析（qq_official 关键坑）**：官方 Bot 接收侧不产真实 At，AstrBot 注入哨兵 `At(qq="qq_official")`，
  目标用户只在 `message_str` 里以 `<@!openid>` 文本出现（字母数字，非纯数字）。
  `utils.find_mentioned_user_id` 必须：跳过 `qq_official` 哨兵 + 文本正则匹配字母数字 openid +
  群消息约定「@机器人 @目标」取最后一个为目标。曾因只匹配 `[0-9]+` 且未跳过哨兵导致 @指令失效（已修）。
- **平台硬限制（插件无法修）**：qq_official 不支持 Reply 段 → 回复无法引用原消息；At 已由文本解析绕过，@人可用。
- **⚠️ qq_official 原生按钮（2026-10-13 踩坑→修复）**：AstrBot `qq_official` 适配器 `_post_send`/`_parse_to_qqofficial`
  只处理 Plain/Image/Record，Button 组件被 `else: 忽略` 丢弃。原生按钮必须走 botpy 键盘 API。
  **致命坑**：botpy 的 `post_group_message(..., keyboard=...)` 封装会注入大量 `null` 字段 → QQ 接口报 `invalid content`
  → 按钮永不渲染、被静默降级为纯文本（日志只有一行 `[菜单] 官方Bot键盘发送失败…` WARNING）。
  **正确做法（已验证，对照 `astrbot_plugin_keyword`）**：直接调 botpy 原生 HTTP 路由
  `await event.bot.api._http.request(route, json=payload)`，最小字段：
  `payload = {"msg_type":2, "markdown":{"content":文本}, "msg_id":源消息id, "keyboard":{...}, "msg_seq":1}`；
  群消息 `Route("POST","/v2/groups/{group_openid}/messages", group_openid=...)`，
  C2C `Route("POST","/v2/users/{openid}/messages", openid=raw.author.user_openid)`。
  键盘按钮 `action.type=2`+`permission.type=2`+`data="/指令"`+`at_bot_show_channel_list=False`+`enter=True`
  （`enter` 不在 botpy 的 Action TypedDict 里，但走 raw JSON 会被转发；不支持时按钮仍会填入输入框）。
  官方 Bot **无需额外后台配置**，按钮能否出现只取决于发送路径是否正确。代码见 `main.py::_send_qq_keyboard`、
  `core/menu.py::build_qq_keyboard`，发送为 best-effort，异常降级纯文本。
- **⚠️ QQ 头像按 QQ 号拉取（2026-10-14 踩坑→修复）**：`draw/utils.py::get_user_avatar` 把 `user_id` 拼进
  `q4.qlogo.cn/headimg_dl?dst_uin={user_id}` 拉 QQ 头像。官方 Bot 下 `user_id` 是 openid（字母数字串）而非 QQ 号，
  请求必败且每次刷 warning。已改为：仅当 `user_id.isdigit() and 5<=len<=12`（像 QQ 号）才发请求，否则静默跳过
  （debug 日志、不报错），状态/背包/图鉴照常渲染（仅不显示头像）。NapCat 数字 QQ 号头像不受影响。

- **⚠️ 拟饵「是否消耗」看 `is_consumable`，不是 `duration_minutes`（2026-10-14 踩坑→修复）**：`fishing_service` 曾只按
  `duration_minutes==0` 判定「一次性鱼饵每次扣1」，导致亮片拟饵/大师拟饵（`is_consumable=False`「无消耗」但 `duration_minutes` 也=0）
  每次钓鱼被扣到归零。已改为按 `is_consumable` 分流：一次性(True)每钓扣1；无限拟饵(False)只加加成、绝不扣库存；
  限时(duration>0)过期才清，且仅 True 才扣。`is_consumable` 是真实持久化字段（`Bait` 模型/`baits` 表/迁移003）。
  钓鱼消耗点仅 `fishing_service.py` 两处；`update_bait_quantity` 在 `quantity<=0` 会 DELETE 行，所以别对无限拟饵调它。

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
