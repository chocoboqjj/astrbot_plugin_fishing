from typing import Dict, Any

from .abstract_effect import AbstractItemEffect
from ...domain.models import User, Item


class StealProtectionRemovalEffect(AbstractItemEffect):
    effect_type = "STEAL_PROTECTION_REMOVAL"

    def apply(
        self, user: User, item_template: Item, payload: Dict[str, Any], quantity: int = 1
    ) -> Dict[str, Any]:
        """
        驱灵香：驱散目标玩家的海灵守护。

        该道具需要一个「目标玩家」，无法仅凭 user 自身信息判断目标，
        因此实际的道具消耗与驱散逻辑由 /驱灵 @用户 指令完成
        （见 handlers/social_handlers.py 的 dispel_protection）。

        这里的职责是「当玩家误用 /使用 驱灵香 时给出准确指引」，
        而不是静默失败——否则玩家买到 6 万金币的道具却不知道正确用法。
        """
        return {
            "success": False,
            "message": (
                f"【{item_template.name}】需要指定目标才能使用。\n"
                "正确用法：/驱灵 @目标用户\n"
                "（该指令会自动消耗 1 个驱灵香）"
            ),
        }
