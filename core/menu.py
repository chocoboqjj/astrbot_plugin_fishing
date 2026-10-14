"""
钓鱼游戏快捷面板（交互优化）。

目标：在 QQ 官方 Bot 下用「可点选」的键盘按钮替代手打指令；其它平台或按钮不可用时，
降级为「编号菜单 + /选 N」的纯文本方案，仍比手打长指令省力。

- MENU_ITEMS：常用玩家动作（按使用频率排序，全部为无参指令，最多 10 项）。
- build_menu_text()：编号菜单文本。
- get_menu_cmd(index)：序号 → 指令名。
- build_qq_keyboard()：构造 QQ 官方 Bot 键盘 JSON（best-effort，失败返回 None）。
"""

from typing import Dict, List, Optional

# 常用玩家动作（label 用于按钮/展示，cmd 为指令名，method 为 FishingPlugin 上的命令方法名）。
# 仅收录「无参数」的日常指令，保证 /选 N 可直接分发执行。
MENU_ITEMS: List[Dict[str, str]] = [
    {"label": "🎣 钓鱼", "cmd": "钓鱼", "method": "fish", "desc": "消耗金币钓一次鱼"},
    {"label": "📅 签到", "cmd": "签到", "method": "sign_in", "desc": "每日签到领奖"},
    {"label": "💰 状态", "cmd": "状态", "method": "state", "desc": "查看金币/装备"},
    {"label": "🎒 背包", "cmd": "背包", "method": "user_backpack", "desc": "查看所有物品"},
    {"label": "🛒 商店", "cmd": "商店", "method": "shop", "desc": "浏览全部商店"},
    {"label": "🏪 市场", "cmd": "市场", "method": "market", "desc": "交易所挂单浏览"},
    {"label": "🎰 抽卡", "cmd": "抽卡", "method": "gacha", "desc": "召唤卡池"},
    {"label": "🐟 鱼塘", "cmd": "鱼塘", "method": "pond", "desc": "查看我的鱼"},
    {"label": "🏆 排行", "cmd": "排行榜", "method": "ranking", "desc": "各类榜单"},
    {"label": "📖 图鉴", "cmd": "鱼类图鉴", "method": "fish_pokedex", "desc": "已收集鱼类"},
]

# 官方 Bot 键盘每行按钮数（官方限制 5×5，这里 3 个一行，10 项 = 4 行）
_BUTTONS_PER_ROW = 3

# 官方规范：render_data.label / visited_label 最多 10 字符
# 参考：https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/msg-btn.html
_LABEL_MAX = 10


def build_menu_text() -> str:
    """生成编号菜单文本（纯文本降级方案用）。"""
    lines = ["🎮 钓鱼快捷面板（回复「/选 N」即可执行对应指令）："]
    for i, item in enumerate(MENU_ITEMS, 1):
        lines.append(f"{i}. {item['label']}  →  /{item['cmd']}")
    lines.append("")
    lines.append("例：发送「/选 1」即开始钓鱼。")
    lines.append("📱 QQ 官方 Bot 下可直接点上方按钮，无需手打。")
    return "\n".join(lines)


def get_menu_cmd(index: int) -> Optional[str]:
    """序号（1 基）→ 指令名；越界返回 None。"""
    if 1 <= index <= len(MENU_ITEMS):
        return MENU_ITEMS[index - 1]["cmd"]
    return None


def get_menu_method(index: int) -> Optional[str]:
    """序号（1 基）→ FishingPlugin 命令方法名；越界返回 None。"""
    if 1 <= index <= len(MENU_ITEMS):
        return MENU_ITEMS[index - 1]["method"]
    return None


def build_qq_keyboard() -> "Optional[dict]":
    """
    构造 QQ 官方 Bot 键盘 payload（dict，直接挂到 markdown 消息的 keyboard 字段）。

    严格对齐官方「消息按钮」协议（https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/msg-btn.html）：
    - keyboard 长格式 = {"content": {"rows": [{"buttons": [...]}]}}，最多 5 行 × 每行 5 个按钮。
    - 每个 button：id（键盘内唯一）、render_data.label/visited_label（必填，最多 10 字符）、
      render_data.style（0 灰 / 1 蓝）、action.type=2（指令按钮，自动在输入框插入 @bot data）、
      action.permission.type=2（所有人可点）、action.data（指令内容）、
      action.enter（点击直接自动发送，仅单聊可用；群聊下被忽略，按钮仅把指令填入输入框）。
    - 键盘必须挂在 msg_type=2 的 markdown 消息上，且走 botpy 原生 HTTP 路由
      （bot.api._http.request，见 main.py::_send_qq_keyboard）才能绕开 botpy 封装注入的
      null 字段导致接口校验失败（invalid content）。

    返回 {"content": {"rows": [...]}}；失败时返回 None。
    """
    try:
        rows: List[Dict] = []
        button_id = 0
        for i in range(0, len(MENU_ITEMS), _BUTTONS_PER_ROW):
            buttons = []
            for item in MENU_ITEMS[i : i + _BUTTONS_PER_ROW]:
                button_id += 1
                label = item["label"]
                if len(label) > _LABEL_MAX:
                    label = label[: _LABEL_MAX] + "…"
                # 第一个（钓鱼）作为主按钮高亮为蓝色，其余灰色
                style = 1 if button_id == 1 else 0
                buttons.append(
                    {
                        "id": str(button_id),
                        "render_data": {
                            "label": label,
                            "visited_label": label,
                            "style": style,
                        },
                        "action": {
                            "type": 2,  # 指令按钮：自动在输入框插入 @bot data
                            "permission": {"type": 2},  # 所有人可点
                            "data": "/" + item["cmd"],  # 点击/自动发送的内容（@bot 由客户端自动加）
                            "at_bot_show_channel_list": False,  # 不弹频道选择器，直接填充 data（官方已标记弃用，保留为默认行为）
                            "enter": True,  # 点击后把 data 作为消息自动发送（等同手打并回车；群聊下被忽略）
                        },
                    }
                )
            rows.append({"buttons": buttons})
        return {"content": {"rows": rows}}
    except Exception:
        return None
