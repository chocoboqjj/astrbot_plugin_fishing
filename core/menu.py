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


def build_qq_keyboard() -> Optional[str]:
    """
    构造 QQ 官方 Bot 键盘 JSON 字符串（best-effort）。

    按钮 action.type=2 + enter=true：点击后把 data（指令文本）作为消息发给机器人，
    由 AstrBot 正常分发执行，等同用户手打该指令。失败返回 None。
    """
    try:
        import json

        rows: List[Dict] = []
        for i in range(0, len(MENU_ITEMS), _BUTTONS_PER_ROW):
            buttons = []
            for j, item in enumerate(MENU_ITEMS[i : i + _BUTTONS_PER_ROW]):
                buttons.append(
                    {
                        "id": str(len(rows) * _BUTTONS_PER_ROW + j + 1),
                        "render_data": {
                            "label": item["label"],
                            "visited_label": item["label"],
                            "style": 1,  # 1=蓝（主按钮）
                        },
                        "action": {
                            "type": 2,  # 回调并发送
                            "permission": {"type": 1},  # 所有人可点
                            "data": "/" + item["cmd"],
                            "enter": True,  # 点击后把 data 作为消息发送
                            "reply": False,
                        },
                    }
                )
            rows.append({"buttons": buttons})
        return json.dumps({"rows": rows}, ensure_ascii=False)
    except Exception:
        return None
