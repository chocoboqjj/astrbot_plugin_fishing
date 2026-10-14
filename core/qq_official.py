"""QQ 官方 Bot（qq_official）事件检测与 openid 路由提取工具。

背景（2026-10-14 实测排障）：
  在部分 AstrBot 版本 / 配置下，qq_official 适配器传入的
  ``event.message_obj.raw_message`` 并不一定是 botpy 原生的 ``GroupMessage`` /
  ``C2CMessage`` 类型（``isinstance`` 判定为 False）；同时 ``platform_meta.platform_name``
  也不一定是精确的 ``"qq_official"`` 字符串。因此旧代码两处检测（菜单按钮 main.py、
  头像 draw/utils.py）会同时失效——表现为「官方 Bot 只看到纯文本菜单、头像也拉不到」。

  本模块改用「多信号容错」检测，并对真实事件形态打印 debug 日志，便于在仍然失败时
  从日志里直接看到 raw_message 的真实结构，从而进一步收敛。

  检测信号（任一命中即视为官方 Bot 上下文）：
    a. raw_message 是 botpy 原生 GroupMessage / C2CMessage（理想情况）
    b. raw_message 的类名 / 模块名含 qq / botpy / group / c2c / official
    c. raw_message 携带 group_openid 或 author.user_openid 字段
       （兼容对象属性与 dict 键两种形态，并兼容 QQ 网关事件外层 d/data 包裹）
    d. platform_name 子串含 official / qq_official
"""
from typing import Any, Optional, Tuple

try:
    from astrbot.api import logger
except Exception:  # 非框架环境（如单测）兜底
    import logging

    logger = logging.getLogger("astrbot_plugin_fishing")


def _safe_get(raw: Any, *path: str) -> Optional[str]:
    """沿属性 / 字典键逐级取值，任一缺失返回 None。

    额外兼容 QQ 网关事件常见的外层包裹：若 raw 是 dict 且顶层含 ``d`` / ``data`` /
    ``event`` 其中之一（且为 dict），则先下钻一层再取值。这样无论适配器把消息放在
    事件对象顶层还是包在 ``d`` 里，都能取到 openid。
    """
    cur: Any = raw
    if isinstance(cur, dict) and path:
        for wrap in ("d", "data", "event"):
            wrapped = cur.get(wrap)
            if isinstance(wrapped, dict):
                cur = wrapped
                break

    for key in path:
        if cur is None:
            return None
        # 先试属性访问
        val = getattr(cur, key, None)
        # 再试 dict 键访问
        if val is None and isinstance(cur, dict):
            val = cur.get(key)
        if val is None:
            return None
        cur = val
    return val if isinstance(cur, str) and cur else None


def get_sender_openid(raw: Any) -> Optional[str]:
    """从官方 Bot 原始消息取发送者 openid（用于拉头像 / C2C 路由）。"""
    return _safe_get(raw, "author", "user_openid") or _safe_get(raw, "user_openid")


def get_group_openid(raw: Any) -> Optional[str]:
    """从官方 Bot 群消息取 group_openid（用于群消息路由）。"""
    return _safe_get(raw, "group_openid")


def get_message_id(raw: Any) -> Optional[str]:
    """从原始消息取消息 id（用于被动回复引用）。"""
    return _safe_get(raw, "id")


def get_official_route_target(raw: Any) -> Tuple[Optional[str], Optional[str]]:
    """推断官方 Bot 发送路由。

    返回 ``(kind, target)``：
      - ``("group", group_openid)`` 群消息 → POST /v2/groups/{group_openid}/messages
      - ``("c2c",   user_openid)`` 单聊 / 群内取发送者 → POST /v2/users/{openid}/messages
      - ``(None,    None)``        无法识别
    """
    g = get_group_openid(raw)
    if g:
        return ("group", g)
    u = get_sender_openid(raw)
    if u:
        return ("c2c", u)
    return (None, None)


def is_official_bot_event(event: Any) -> bool:
    """多信号判断消息是否来自 QQ 官方 Bot。

    命中后立即打印一行 debug 日志，记录各信号取值与 raw_message 的真实类型 / 截断 repr，
    便于在仍然失败时定位根因。
    """
    raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
    platform_name = getattr(getattr(event, "platform_meta", None), "platform_name", "") or ""

    # 信号 a：botpy 原生类型
    try:
        import botpy.message  # type: ignore

        botpy_isinstance = bool(
            raw is not None
            and isinstance(raw, (botpy.message.GroupMessage, botpy.message.C2CMessage))
        )
    except Exception:
        botpy_isinstance = "botpy_unavailable"

    # 信号 b：类名 / 模块名
    raw_name = type(raw).__name__ if raw is not None else "None"
    raw_mod = getattr(type(raw), "__module__", "") if raw is not None else ""
    classname_hit = any(
        k in (raw_name.lower() + raw_mod.lower())
        for k in ("qq", "botpy", "group", "c2c", "official")
    )

    # 信号 c：携带 openid 字段
    has_openid_fields = get_official_route_target(raw)[0] is not None

    # 信号 d：platform_name 子串
    platform_hit = ("official" in platform_name.lower()) or ("qq_official" in platform_name.lower())

    result = bool(
        botpy_isinstance is True or classname_hit or has_openid_fields or platform_hit
    )

    raw_repr = repr(raw)
    if len(raw_repr) > 600:
        raw_repr = raw_repr[:600] + "...(truncated)"
    logger.debug(
        f"[detect] is_official_bot={result} | raw_type={raw_mod}.{raw_name} "
        f"botpy={botpy_isinstance} cls_hit={classname_hit} openid_hit={has_openid_fields} "
        f"platform={platform_name!r}(hit={platform_hit}) | raw_repr={raw_repr}"
    )
    return result
