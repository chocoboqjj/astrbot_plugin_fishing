# astrbot_plugin_fishing 项目长期约定

## 提交规范（用户明确要求）
- **每次提交都必须同步更新 `README.md`**，使文档与实际功能/配置保持一致。
  （用户原话：「每次提交readme也记得更新」）
- 提交前应确认：README 已反映本轮改动的玩法、配置、命令与依赖变化。
- 版本号遵循 `metadata.yaml` / `README.md` / `CHANGELOG.md` 三处同步（当前 2.4.17）。

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
- **⚠️ qq_official 原生按钮（2026-10-13 踩坑→修复→v2.4.13 对齐官方协议）**：AstrBot `qq_official` 适配器 `_post_send`/`_parse_to_qqofficial`
  只处理 Plain/Image/Record，Button 组件被 `else: 忽略` 丢弃。原生按钮必须走 botpy 键盘 API。
  **致命坑**：botpy 的 `post_group_message(..., keyboard=...)` 封装会注入大量 `null` 字段 → QQ 接口报 `invalid content`
  → 按钮永不渲染、被静默降级为纯文本（日志只有一行 `[菜单] 官方Bot键盘发送失败…` WARNING）。
  **正确做法（已验证，对照 `astrbot_plugin_keyword`）**：直接调 botpy 原生 HTTP 路由
  `await event.bot.api._http.request(route, json=payload)`，最小字段：
  `payload = {"msg_type":2, "markdown":{"content":文本}, "msg_id":源消息id, "keyboard":{...}, "msg_seq":1}`；
  群消息 `Route("POST","/v2/groups/{group_openid}/messages", group_openid=...)`，
  C2C `Route("POST","/v2/users/{openid}/messages", openid=raw.author.user_openid)`。
  官方「消息按钮」协议（`bot.q.qq.com/.../msg-btn.html`，v2.4.13 起严格对齐）：
  - 键盘长格式 `{"content": {"rows": [{"buttons": [...]}]}}`，**最多 5 行 × 每行 5 个**按钮。
  - 每个 button：`id`(键盘内唯一) + `render_data{label, visited_label(必填), style(0灰/1蓝)}` + `action{type, permission, data, enter}`。
  - `render_data.label` / `visited_label` **最多 10 字符**（按钮文案控制在 10 字内）。
  - `action.type=2`(指令按钮：客户端自动在输入框插入 `@bot data`) + `action.permission.type=2`(所有人可点) +
    `action.data="指令"（v2.4.16 起去掉 / 前缀，原为 /指令；客户端仍自动补 @bot）` + `action.enter=True`(单聊点击直接自动发送；**群聊下 enter 被忽略**，按钮仅把指令填入输入框，玩家需手动发送)。
  - **⚠️ 触发前缀坑（v2.4.16 用户要求 data 去 `/`）**：官方 Bot 点按钮时客户端把 `data` 作为消息发出，AstrBot 按命令前缀匹配。默认前缀 `/` → 仅 `/钓鱼` 触发；若 `data=钓鱼` 且前缀仍是 `/`，**点击不触发指令**。需把 AstrBot `command_prefix` 设为空字符串（官方 Bot 用 `@bot` 提及已能区分，空前缀常见），否则按钮点了无反应。面板纯文本（`build_menu_text`）同步精简：去掉示例句与「📱 可直接点上方按钮」说明行，列表不再逐行带「→ /指令」。
  - `at_bot_show_channel_list` 官方已标记弃用，保留 `False`（默认行为，无害）。
  - 主操作「🎣 钓鱼」置 `style=1`(蓝主按钮)，其余 `style=0`(灰)。
  - 官方 Bot **无需额外后台配置**，按钮能否出现只取决于发送路径是否正确。代码见 `main.py::_send_qq_keyboard`、
    `core/menu.py::build_qq_keyboard`；发送为 best-effort，异常降级纯文本。结构经脚本逐项断言（行/列上限、字段必填、label≤10、取值）通过。
  - **⚠️ 检测坑（v2.4.14 误判→v2.4.15 彻底改成多信号容错）**：`/面板` 早期用 `platform_name == "qq_official"` 精确匹配当门，
    v2.4.14 改成看 `raw_message` 是否为 botpy `GroupMessage`/`C2CMessage`。**但用户实测其环境里这个 isinstance 判定也是 False**——
    于是 v2.4.14 后「头像也拉不到」被坐实：按钮与头像**共用同一个失效信号** `isinstance(raw_message, botpy.GroupMessage/C2CMessage)`，
    两处同时静默跳过（表现：`/面板` 只出纯文本、`get_user_avatar` 永远走不到官方接口）。
    **v2.4.15 根因修复**：新增共享模块 `core/qq_official.py` 的 `is_official_bot_event(event)`，多信号容错——
    ① botpy 原生类型；② `raw_message` 类名/模块名含 qq/botpy/group/c2c/official；③ `raw_message` 带 `group_openid` 或
    `author.user_openid`（兼容对象属性与 dict 键，并兼容 QQ 网关事件外层 `d`/`data` 包裹）；④ `platform_name` 含 official/qq_official
    子串——任一命中即官方 Bot。键盘发送用 `get_official_route_target(raw)` 选群(`group_openid`)/单聊(`user_openid`)路由；
    头像用 `get_sender_openid(raw)` 取 URL；二者复用同一检测。`is_official_bot_event` 每次调用打一行 `[detect]` debug
    （含 `raw_type`、各信号命中、`platform_name`、`raw_message` 截断 repr≤600 字），**若仍不生效，让用户贴运行日志里的 `[detect]` 行即可定位真实事件结构**。
    `main.py::_is_qq_official` 现仅委托 `is_official_bot_event`；`_send_qq_keyboard` 静默失败点补 `[菜单]` debug，发送异常 `logger.warning`。
- **⚠️ QQ 头像（2026-10-14 踩坑→修复→增强）**：`draw/utils.py::get_user_avatar(user_id, data_dir, avatar_size, event=None)`：
  - NapCat 等**纯数字 QQ 号**（`user_id.isdigit() and 5<=len<=12`）→ 走 `q4.qlogo.cn/headimg_dl?dst_uin={user_id}`。
  - **官方 Bot(openid)**：`user_id` 是 openid 而非 QQ 号，不能走 qlogo；但渲染时 handler 透传 `event`，
    在官方 Bot 上下文（`core.qq_official.is_official_bot_event` 多信号命中，v2.4.15 起不再依赖 botpy `isinstance`）时，
    调官方接口 `GET /v2/users/{openid}`（`openid` 由 `get_sender_openid(raw)` 取，兼容对象/dict/`d`包裹）取 `avatar` URL 再下载
    （24h 缓存；`_resolve_official_avatar` + `_extract_avatar_from_userinfo`，后者兼容 `avatar` / `user.avatar` / `data.*` 多种返回结构）。
  - 非官方 Bot / 无 `event` / 接口异常 → **静默降级**（debug 日志、不报错），状态/背包/图鉴照常渲染（仅不显示头像）。
  - 调用链：`common_handlers`(状态) / `inventory_handlers`(背包) / `fishing_handlers`(图鉴) → `draw_state_image`/`draw_backpack_image`/`draw_pokedex` 均新增 `event=None` 并透传给 `get_user_avatar`。

- **⚠️ 拟饵「是否消耗」看 `is_consumable`，不是 `duration_minutes`（2026-10-14 踩坑→修复）**：`fishing_service` 曾只按
  `duration_minutes==0` 判定「一次性鱼饵每次扣1」，导致亮片拟饵/大师拟饵（`is_consumable=False`「无消耗」但 `duration_minutes` 也=0）
  每次钓鱼被扣到归零。已改为按 `is_consumable` 分流：一次性(True)每钓扣1；无限拟饵(False)只加加成、绝不扣库存；
  限时(duration>0)过期才清，且仅 True 才扣。`is_consumable` 是真实持久化字段（`Bait` 模型/`baits` 表/迁移003）。
  钓鱼消耗点仅 `fishing_service.py` 两处；`update_bait_quantity` 在 `quantity<=0` 会 DELETE 行，所以别对无限拟饵调它。

- **⚠️ 擦弹「已用/上限/剩余」计数口径（2026-10-14 排查）**：
  - **两套计数器**：`/擦弹` 执行与状态图用 `users.wipe_bomb_attempts_today`（用户字段，新一天首次擦弹时按 `last_wipe_bomb_date` 重置）；
    【擦弹许可证】回执与「剩余」用 `wipe_bomb_log` 表今日行数（`get_wipe_bomb_log_count_today`，`contribution_amount>0`）。
    两个计数在 `perform_wipe_bomb` 内锁步（+1 字段 + 写 1 行日志），被拦截的超上限擦弹不写日志，故不会脱节。**通用日志 `add_log` 写 `contribution_amount=0`，不计入**。
  - **上限公式**：`get_wipe_bomb_max_attempts` = 基础(`max_attempts_per_day`,默认3) + buff(`WIPE_BOMB_ATTEMPTS_BOOST` 累加) + **阶级加成(`wipe_bomb_bonus`，各阶级 +1~+8)**。
  - **历史坑（v2.4.12 修）**：【擦弹许可证】回执的「上限」曾只算 `基础 + buff`，**漏掉阶级加成**，导致有阶级加成的玩家回执剩余被少算（如基础3+许可3+阶级1，回执显示上限6、剩2，实际可擦上限7、剩3）。
    v2.4.12 起回执改调 `game_mechanics_service.get_wipe_bomb_max_attempts(user_id, user)`，与 `/擦弹`、状态图三处对齐。
    `game_mechanics_service` 已在 `main.py` 的 `EffectManager.discover_and_register` 依赖字典里，效果类 `__init__` 取 `kwargs["game_mechanics_service"]` 即可。
  - **排查「已用」是否真实**：仓库根 `diagnose_wipe.py`（一次性工具，`python diagnose_wipe.py <fish.db> [user_id]`）列出今日 `wipe_bomb_log` 逐条时间戳 + `users.wipe_bomb_attempts_today` + 当前 buff，直接核对。

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
