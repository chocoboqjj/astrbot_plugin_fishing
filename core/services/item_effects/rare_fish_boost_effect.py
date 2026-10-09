import json
from datetime import datetime, timedelta
from typing import Dict, Any

from .abstract_effect import AbstractItemEffect
from ...domain.models import User, Item, UserBuff
from ...utils import get_now

# 稀有鱼加成的倍率上限。与 fishing_service 中读取的
# fishing.rare_chance_max_boost（默认 0.8）保持一致：
# buff 本身也要封顶，否则玩家叠加药水能突破钓鱼侧的封顶防线。
MAX_BOOST_MULTIPLIER = 0.8


class RareFishBoostEffect(AbstractItemEffect):
    effect_type = "RARE_FISH_BOOST"

    def apply(
        self, user: User, item_template: Item, payload: Dict[str, Any], quantity: int = 1
    ) -> Dict[str, Any]:
        duration_seconds = payload.get("duration_seconds", 600)
        # 注意：payload 中的 multiplier 语义是「稀有多大提升比例」（如 0.05 = +5%），
        # 与 fishing_service 中 rare_chance += payload.multiplier 的处理一致。
        multiplier = float(payload.get("multiplier", 0.05))

        # 单次叠加即封顶，避免玩家囤积药水一次性刷出极端倍率
        single_use = min(multiplier, MAX_BOOST_MULTIPLIER)
        if quantity > 1:
            # 批量使用时按份数累加，但同样受上限约束
            effective_multiplier = min(single_use * quantity, MAX_BOOST_MULTIPLIER)
        else:
            effective_multiplier = single_use

        total_duration_seconds = duration_seconds * quantity

        existing_buff = self.buff_repo.get_active_by_user_and_type(
            user.user_id, "RARE_FISH_BOOST"
        )

        now = get_now().replace(tzinfo=None)
        if existing_buff:
            # 时长可以叠加（喝药水续期），但倍率必须封顶
            try:
                current_payload = json.loads(existing_buff.payload or "{}")
            except (TypeError, ValueError):
                current_payload = {}
            current_multiplier = float(current_payload.get("multiplier", 0.0))
            new_multiplier = min(current_multiplier + effective_multiplier, MAX_BOOST_MULTIPLIER)

            start_time = max(now, existing_buff.expires_at)
            new_expires_at = start_time + timedelta(seconds=total_duration_seconds)

            existing_buff.expires_at = new_expires_at
            existing_buff.payload = json.dumps({"multiplier": new_multiplier})
            self.buff_repo.update(existing_buff)

            total_remaining_seconds = (new_expires_at - now).total_seconds()
            total_remaining_minutes = int(total_remaining_seconds / 60)

            capped = new_multiplier >= MAX_BOOST_MULTIPLIER
            suffix = "（已达上限）" if capped else f"（稀有 +{new_multiplier * 100:.1f}%）"

            return {
                "success": True,
                "message": f"✨ 幸运效果已叠加！总持续时间延长至 {total_remaining_minutes} 分钟{suffix}。",
            }
        else:
            new_expires_at = now + timedelta(seconds=total_duration_seconds)
            new_buff = UserBuff(
                id=None,
                user_id=user.user_id,
                buff_type="RARE_FISH_BOOST",
                payload=json.dumps({"multiplier": effective_multiplier}),
                started_at=now,
                expires_at=new_expires_at,
            )
            self.buff_repo.add(new_buff)

            total_minutes = total_duration_seconds // 60
            capped = effective_multiplier >= MAX_BOOST_MULTIPLIER
            suffix = "（已达上限）" if capped else f"（稀有 +{effective_multiplier * 100:.1f}%）"
            return {
                "success": True,
                "message": f"✨ 接下来的 {total_minutes} 分钟内，钓到稀有鱼的概率提升了{suffix}！",
            }
