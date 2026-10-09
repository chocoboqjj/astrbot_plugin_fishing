import json
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from datetime import datetime

from ..domain.models import User, FishingZone
from ..repositories.abstract_repository import AbstractItemTemplateRepository, AbstractInventoryRepository


class FishingZoneStrategy(ABC):
    """钓鱼区域策略的抽象基类"""

    # 分布数组的标准长度：对应 [1星, 2星, 3星, 4星, 5星, 6星及以上]
    DIST_LENGTH = 6

    def __init__(self, item_template_repo: AbstractItemTemplateRepository, config: Dict[str, Any],
                 zone_config: Dict[str, Any]):
        self.item_template_repo = item_template_repo
        self.config = config
        self.zone_config = zone_config

    @abstractmethod
    def get_fish_rarity_distribution(self, user: User) -> List[float]:
        """根据用户和区域配置计算鱼的稀有度分布"""
        pass

    def _normalize_distribution(self, raw: Any) -> List[float] | None:
        """把配置中的分布补齐/截断为标准长度，并做合法性校验。

        背景：历史上各区域的 ``rarity_distribution`` 只写了 5 个元素，
        旧实现直接 ``while len < 6: append(0.0)`` 补齐，导致第 6 位（6星及以上）
        恒为 0 —— 结果 4 种 6 星 + 3 种 7 星 + 2 种 8 星鱼永远钓不到。

        现在统一走本方法：按末尾补 0 / 截断，并确保各项非负、总和接近 1。
        返回 None 表示配置缺失或非法，应回退到策略默认分布。
        """
        if not isinstance(raw, (list, tuple)) or not raw:
            return None

        dist = [float(v) if isinstance(v, (int, float)) else 0.0 for v in raw]

        if len(dist) < self.DIST_LENGTH:
            dist = dist + [0.0] * (self.DIST_LENGTH - len(dist))
        elif len(dist) > self.DIST_LENGTH:
            dist = dist[: self.DIST_LENGTH]

        # 负值视为非法
        if any(v < 0 for v in dist):
            return None

        total = sum(dist)
        if total <= 0:
            return None

        # 归一化，保证 random.choices 的权重语义正确
        return [v / total for v in dist]


class Zone1Strategy(FishingZoneStrategy):
    """区域一：新手港湾"""

    def get_fish_rarity_distribution(self, user: User) -> List[float]:
        # 新手区域：主1-4 星，少量 5 星，无 6+ 星（让玩家先熟悉基础节奏）
        dist = self._normalize_distribution(self.zone_config.get("rarity_distribution"))
        if dist is None:
            return [0.60, 0.30, 0.08, 0.02, 0.0, 0.0]
        return dist


class Zone2Strategy(FishingZoneStrategy):
    """区域二：深海峡谷"""

    def get_fish_rarity_distribution(self, user: User) -> List[float]:
        # 深海峡谷：4 星概率提升，极小概率触及 6 星
        dist = self._normalize_distribution(self.zone_config.get("rarity_distribution"))
        if dist is None:
            return [0.40, 0.30, 0.20, 0.09, 0.01, 0.003]
        return dist


class Zone3Strategy(FishingZoneStrategy):
    """区域三：传说之海"""

    def get_fish_rarity_distribution(self, user: User) -> List[float]:
        # 传说之海：5 星大幅提升，可稳定钓到 6 星（1.2%）
        dist = self._normalize_distribution(self.zone_config.get("rarity_distribution"))
        if dist is None:
            return [0.30, 0.20, 0.20, 0.19, 0.098, 0.012]
        return dist


class CustomZoneStrategy(FishingZoneStrategy):
    """自定义区域（含无尽深渊）"""

    def get_fish_rarity_distribution(self, user: User) -> List[float]:
        # 自定义区域完全依赖配置，缺失时回退到偏向高星的默认分布
        dist = self._normalize_distribution(self.zone_config.get("rarity_distribution"))
        if dist is None:
            return [0.16, 0.16, 0.16, 0.16, 0.20, 0.16]
        return dist


class FishingZoneService:
    def __init__(self, item_template_repo: AbstractItemTemplateRepository,
                 inventory_repo: AbstractInventoryRepository,
                 config: Dict[str, Any]):
        self.item_template_repo = item_template_repo
        self.inventory_repo = inventory_repo
        self.config = config
        self.strategies = self._load_strategies()

    def _load_strategies(self) -> Dict[int, FishingZoneStrategy]:
        zones = self.inventory_repo.get_all_zones()
        strategies = {}
        for zone in zones:
            if not zone.is_active:
                continue

            from ..utils import get_now
            now = get_now()
            if zone.available_from and now < zone.available_from:
                continue
            if zone.available_until and now > zone.available_until:
                continue
            
            zone.specific_fish_ids = self.inventory_repo.get_specific_fish_ids_for_zone(zone.id)
            
            zone_config = zone.configs if zone.configs else {}
            if zone.id == 1:
                strategies[zone.id] = Zone1Strategy(self.item_template_repo, self.config, zone_config)
            elif zone.id == 2:
                strategies[zone.id] = Zone2Strategy(self.item_template_repo, self.config, zone_config)
            elif zone.id == 3:
                strategies[zone.id] = Zone3Strategy(self.item_template_repo, self.config, zone_config)
            else:
                # 对于自定义区域（ID > 3），使用专门的自定义策略
                strategies[zone.id] = CustomZoneStrategy(self.item_template_repo, self.config, zone_config)
        return strategies

    def get_strategy(self, zone_id: int) -> FishingZoneStrategy:
        strategy = self.strategies.get(zone_id)
        if not strategy:
            # 默认返回区域1的策略
            return self.strategies.get(1)
        return strategy

    def get_all_zones(self) -> List[Dict[str, Any]]:
        zones = self.inventory_repo.get_all_zones()
        zones_data = []
        for zone in zones:
            specific_fish_ids = self.inventory_repo.get_specific_fish_ids_for_zone(zone.id)
            zones_data.append({
                "id": zone.id,
                "name": zone.name,
                "description": zone.description,
                "daily_rare_fish_quota": zone.daily_rare_fish_quota,
                "configs": zone.configs,
                "is_active": zone.is_active,
                "available_from": zone.available_from.isoformat() if zone.available_from else None,
                "available_until": zone.available_until.isoformat() if zone.available_until else None,
                "specific_fish_ids": specific_fish_ids,
                "required_item_id": zone.required_item_id,
                "requires_pass": zone.requires_pass,
                "fishing_cost": zone.fishing_cost
            })
        return zones_data

    def create_zone(self, zone_data: Dict[str, Any]) -> Dict[str, Any]:
        new_zone = self.inventory_repo.create_zone(zone_data)
        self.strategies = self._load_strategies()  # Reload strategies
        return {"id": new_zone.id, "name": new_zone.name}

    def update_zone(self, zone_id: int, zone_data: Dict[str, Any]):
        self.inventory_repo.update_zone(zone_id, zone_data)
        if 'specific_fish_ids' in zone_data:
            self.inventory_repo.update_specific_fish_for_zone(zone_id, zone_data['specific_fish_ids'])
        self.strategies = self._load_strategies()  # Reload strategies

    def delete_zone(self, zone_id: int):
        self.inventory_repo.delete_zone(zone_id)
        self.strategies = self._load_strategies()  # Reload strategies
