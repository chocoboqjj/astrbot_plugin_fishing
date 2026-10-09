"""
钓鱼阶级服务（段位制 · 纯增益型）

设计约定
--------
· 段位制：单一纵向阶梯，按「双门槛」自动晋升、**只升不降**。
· 双门槛 = 累计钓鱼次数 + 图鉴收集数，两项需**同时**满足。
  只用次数的话自动钓鱼挂机即可满阶；加入图鉴门槛后高阶被「收集深度」卡住。
· 纯增益型特权：仅提供税收折扣 / 商店折扣 / 擦弹次数加成 / 称号，
  **不锁定任何已有内容**（区域、鱼塘档位、精炼等级均不受限），老玩家零风险。

性能约定
--------
`go_fish` 是热路径，因此 `check_promotion()` 做了两级短路：
  1. 若累计钓鱼次数尚未达到下一阶门槛，直接返回，不查图鉴；
  2. 只有次数跨过门槛时才做一次图鉴 COUNT 查询。
"""

from typing import Any, Dict, List, Optional

from astrbot.api import logger


class FishingClassService:
    """钓鱼阶级的判定、晋升与特权查询。"""

    def __init__(
        self,
        user_repo,
        log_repo,
        inventory_repo,
        item_template_repo,
        achievement_repo,
        config: Dict[str, Any],
    ):
        self.user_repo = user_repo
        self.log_repo = log_repo
        self.inventory_repo = inventory_repo
        self.item_template_repo = item_template_repo
        self.achievement_repo = achievement_repo
        self.config = config or {}

    # ------------------------------------------------------------------
    # 配置读取
    # ------------------------------------------------------------------
    @property
    def class_config(self) -> Dict[str, Any]:
        cfg = self.config.get("fishing_class", {})
        return cfg if isinstance(cfg, dict) else {}

    @property
    def enabled(self) -> bool:
        return bool(self.class_config.get("enabled", True))

    def get_tiers(self) -> List[Dict[str, Any]]:
        """返回按 level 升序排列的阶级表。"""
        tiers = self.class_config.get("tiers", [])
        if not isinstance(tiers, list):
            return []
        valid = [t for t in tiers if isinstance(t, dict)]
        return sorted(valid, key=lambda t: int(t.get("level", 0)))

    def get_tier(self, level: int) -> Optional[Dict[str, Any]]:
        for tier in self.get_tiers():
            if int(tier.get("level", 0)) == int(level):
                return tier
        return None

    # ------------------------------------------------------------------
    # 数据获取
    # ------------------------------------------------------------------
    def get_pokedex_count(self, user_id: str) -> int:
        """图鉴已收集种类数。"""
        try:
            stats = self.log_repo.get_user_fish_stats(user_id)
            return len(stats) if stats else 0
        except Exception as e:
            logger.warning(f"[阶级] 获取用户 {user_id} 图鉴数失败: {e}")
            return 0

    def get_max_refine_level(self, user_id: str) -> int:
        """最高精炼等级（取当前装备鱼竿与饰品中的较大值，取不到则为 0）。"""
        best = 0
        try:
            rod = self.inventory_repo.get_user_equipped_rod(user_id)
            if rod is not None:
                best = max(best, int(getattr(rod, "refine_level", 0) or 0))
            acc = self.inventory_repo.get_user_equipped_accessory(user_id)
            if acc is not None:
                best = max(best, int(getattr(acc, "refine_level", 0) or 0))
        except Exception as e:
            logger.debug(f"[阶级] 获取用户 {user_id} 精炼等级失败: {e}")
        return best

    def compute_score(self, fish_count: int, pokedex: int, max_refine: int = 0) -> int:
        """钓力值（仅用于展示与排行，不作为晋升门槛）。"""
        weights = self.class_config.get("score_weights", {})
        if not isinstance(weights, dict):
            weights = {}
        return int(
            fish_count * float(weights.get("fish_count", 1))
            + pokedex * float(weights.get("pokedex", 20))
            + max_refine * float(weights.get("refine", 30))
        )

    # ------------------------------------------------------------------
    # 阶级判定
    # ------------------------------------------------------------------
    def determine_level(self, fish_count: int, pokedex: int) -> int:
        """按双门槛计算应得阶级（取满足全部条件的最高阶）。"""
        level = 1
        for tier in self.get_tiers():
            need_count = int(tier.get("fish_count", 0))
            need_pokedex = int(tier.get("pokedex", 0))
            if fish_count >= need_count and pokedex >= need_pokedex:
                level = int(tier.get("level", level))
        return level

    def get_next_tier(self, level: int) -> Optional[Dict[str, Any]]:
        tiers = self.get_tiers()
        for tier in tiers:
            if int(tier.get("level", 0)) > int(level):
                return tier
        return None

    # ------------------------------------------------------------------
    # 晋升
    # ------------------------------------------------------------------
    def check_promotion(self, user_id: str) -> Dict[str, Any]:
        """检查并（若满足）执行晋升。返回结果字典。

        设计为可安全高频调用：绝大多数调用会在第一级短路返回。
        """
        if not self.enabled or not self.user_repo:
            return {"promoted": False}

        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"promoted": False, "reason": "用户不存在"}

        current_level = int(getattr(user, "fishing_class_level", 1) or 1)
        next_tier = self.get_next_tier(current_level)

        # 已达最高阶
        if next_tier is None:
            return {"promoted": False, "level": current_level}

        # 短路 1：次数尚未达到下一阶门槛，直接返回（不查图鉴）
        fish_count = int(getattr(user, "total_fishing_count", 0) or 0)
        need_count = int(next_tier.get("fish_count", 0))
        if fish_count < need_count:
            return {"promoted": False, "level": current_level}

        # 短路 2：次数够了才查图鉴
        pokedex = self.get_pokedex_count(user_id)
        need_pokedex = int(next_tier.get("pokedex", 0))
        if pokedex < need_pokedex:
            return {"promoted": False, "level": current_level}

        new_level = self.determine_level(fish_count, pokedex)
        if new_level <= current_level:
            return {"promoted": False, "level": current_level}

        return self._apply_promotion(user, new_level, fish_count, pokedex)

    def grant_titles_up_to(self, user_id: str, level: int) -> List[str]:
        """补发第 1 阶到 level 阶的全部阶级称号（INSERT OR IGNORE，幂等可重复调用）。"""
        granted: List[str] = []
        if not self.achievement_repo:
            return granted
        for lv in range(1, int(level) + 1):
            tier = self.get_tier(lv)
            if not tier:
                continue
            title_id = int(tier.get("title_id", 0) or 0)
            if title_id <= 0:
                continue
            try:
                self.achievement_repo.grant_title_to_user(user_id, title_id)
                granted.append(str(tier.get("name", lv)))
            except Exception as e:
                logger.warning(f"[阶级] 授予用户 {user_id} 阶级称号 {title_id} 失败: {e}")
        return granted

    def _apply_promotion(self, user, new_level: int, fish_count: int, pokedex: int) -> Dict[str, Any]:
        """写入晋升结果并补发中间档称号。"""
        old_level = int(getattr(user, "fishing_class_level", 1) or 1)
        max_refine = self.get_max_refine_level(user.user_id)

        user.fishing_class_level = new_level
        user.fishing_class_score = self.compute_score(fish_count, pokedex, max_refine)
        self.user_repo.update(user)

        # 补发 1..new_level 的全部阶级称号（幂等），避免跳阶或初始称号漏发
        granted = self.grant_titles_up_to(user.user_id, new_level)

        try:
            if self.log_repo:
                self.log_repo.add_log(
                    user.user_id,
                    "class_promotion",
                    f"钓鱼阶级晋升：{old_level} → {new_level}",
                )
        except Exception as e:
            logger.debug(f"[阶级] 记录晋升日志失败: {e}")

        logger.info(f"[阶级] 用户 {user.user_id} 晋升：{old_level} → {new_level}")

        return {
            "promoted": True,
            "from_level": old_level,
            "level": new_level,
            "name": (self.get_tier(new_level) or {}).get("name", ""),
            "titles_granted": granted,
        }

    # ------------------------------------------------------------------
    # 特权查询
    # ------------------------------------------------------------------
    def _perk_for_user(self, user, key: str, default):
        """从已加载的 user 对象读取特权值（避免调用方重复查库）。"""
        if not self.enabled or user is None:
            return default
        tier = self.get_tier(int(getattr(user, "fishing_class_level", 1) or 1))
        if not tier:
            return default
        return tier.get(key, default)

    def _perk(self, user_id: str, key: str, default):
        if not self.enabled or not self.user_repo:
            return default
        return self._perk_for_user(self.user_repo.get_by_id(user_id), key, default)

    def get_tax_discount(self, user_id: str) -> float:
        """每日资产税折扣，0.10 表示减税 10%。"""
        value = self._perk(user_id, "tax_discount", 0.0)
        return min(max(float(value or 0.0), 0.0), 0.9)

    def get_shop_discount(self, user_id: str) -> float:
        """商店购买折扣，0.05 表示 95 折。"""
        value = self._perk(user_id, "shop_discount", 0.0)
        return min(max(float(value or 0.0), 0.0), 0.9)

    def get_wipe_bomb_bonus(self, user_id: str) -> int:
        """每日擦弹次数加成。"""
        return int(self._perk(user_id, "wipe_bomb_bonus", 0) or 0)

    # --- 以 user 对象为入口的同名特权查询（热路径 / 已持有 user 时使用）---
    def get_tax_discount_for_user(self, user) -> float:
        value = self._perk_for_user(user, "tax_discount", 0.0)
        return min(max(float(value or 0.0), 0.0), 0.9)

    def get_shop_discount_for_user(self, user) -> float:
        value = self._perk_for_user(user, "shop_discount", 0.0)
        return min(max(float(value or 0.0), 0.0), 0.9)

    def get_wipe_bomb_bonus_for_user(self, user) -> int:
        return int(self._perk_for_user(user, "wipe_bomb_bonus", 0) or 0)

    # ------------------------------------------------------------------
    # 展示
    # ------------------------------------------------------------------
    def get_user_class_info(self, user_id: str) -> Dict[str, Any]:
        """返回用于展示的阶级详情（含下一阶进度）。"""
        if not self.user_repo:
            return {"success": False, "message": "用户仓储未初始化"}

        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        fish_count = int(getattr(user, "total_fishing_count", 0) or 0)
        pokedex = self.get_pokedex_count(user_id)
        max_refine = self.get_max_refine_level(user_id)
        level = int(getattr(user, "fishing_class_level", 1) or 1)
        score = self.compute_score(fish_count, pokedex, max_refine)

        tier = self.get_tier(level) or {}
        next_tier = self.get_next_tier(level)
        total_species = int(self.class_config.get("total_fish_species", 112) or 112)

        progress = None
        if next_tier:
            progress = {
                "fish_count": fish_count,
                "fish_count_needed": int(next_tier.get("fish_count", 0)),
                "pokedex": pokedex,
                "pokedex_needed": int(next_tier.get("pokedex", 0)),
                "next_name": next_tier.get("name", ""),
                "next_level": int(next_tier.get("level", 0)),
            }

        return {
            "success": True,
            "enabled": self.enabled,
            "level": level,
            "name": tier.get("name", ""),
            "score": score,
            "fish_count": fish_count,
            "pokedex": pokedex,
            "total_species": total_species,
            "max_refine": max_refine,
            "tax_discount": self.get_tax_discount(user_id),
            "shop_discount": self.get_shop_discount(user_id),
            "wipe_bomb_bonus": self.get_wipe_bomb_bonus(user_id),
            "next": progress,
        }

    def format_class_info(self, user_id: str) -> str:
        """把阶级信息格式化为可直接发送的文本。"""
        info = self.get_user_class_info(user_id)
        if not info.get("success"):
            return f"❌ {info.get('message', '获取阶级信息失败')}"

        if not info.get("enabled"):
            return "ℹ️ 钓鱼阶级系统当前未启用。"

        lines = [
            f"🎖️ 【{info['name']}】第 {info['level']} 阶",
            f"   钓力值：{info['score']}",
            f"   累计钓鱼：{info['fish_count']} 次",
            f"   图鉴收集：{info['pokedex']}/{info['total_species']} 种",
            f"   最高精炼：{info['max_refine']} 级",
        ]
        perks = []
        if info["tax_discount"] > 0:
            perks.append(f"税收减免 {int(info['tax_discount'] * 100)}%")
        if info["shop_discount"] > 0:
            perks.append(f"商店折扣 {int(info['shop_discount'] * 100)}%")
        if info["wipe_bomb_bonus"] > 0:
            perks.append(f"每日擦弹 +{info['wipe_bomb_bonus']}")
        lines.append(f"   当前特权：{'、'.join(perks) if perks else '暂无'}")

        nxt = info.get("next")
        if nxt:
            lines.append(
                f"\n📈 下一阶【{nxt['next_name']}】还需："
                f"\n   钓鱼 {nxt['fish_count']}/{nxt['fish_count_needed']} 次"
                f"\n   图鉴 {nxt['pokedex']}/{nxt['pokedex_needed']} 种"
                f"\n   （两项需同时满足）"
            )
        else:
            lines.append("\n👑 已达到最高阶级。")

        return "\n".join(lines)
