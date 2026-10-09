from ..repositories.abstract_repository import (
    AbstractItemTemplateRepository,
    AbstractGachaRepository,
    AbstractShopRepository,
)
from ..initial_data import (
    FISH_DATA,
    BAIT_DATA,
    ROD_DATA,
    ACCESSORY_DATA,
    TITLE_DATA,
    GACHA_POOL,
    ITEM_DATA,
    SHOP_DATA,
    SHOP_ITEM_DATA,
    GACHA_POOL_ITEMS,
)
from ..domain.models import Item
from astrbot.api import logger


class DataSetupService:
    """负责在首次启动时初始化游戏基础数据。"""

    def __init__(
        self,
        item_template_repo: AbstractItemTemplateRepository,
        gacha_repo: AbstractGachaRepository,
        shop_repo: AbstractShopRepository,
    ):
        """
        初始化数据设置服务。

        Args:
            item_template_repo: 物品模板仓储的实例，用于与数据库交互。
            gacha_repo: 抽卡仓储的实例。
            shop_repo: 商店仓储的实例。
        """
        self.gacha_repo = gacha_repo
        self.item_template_repo = item_template_repo
        self.shop_repo = shop_repo

    def setup_initial_data(self):
        """
        检查并初始化游戏基础数据。

        这是一个**幂等**操作，可以安全地多次调用。每个数据块**独立判断**是否需要初始化，
        因此当某个表已有数据时，只会跳过该块，不会影响其他块的补齐。

        背景：早期版本在此处用一个「鱼类表非空则整体 return」的判断，
        导致一旦数据库里已有鱼，商店 / 卡池 / 道具 / 称号 就再也不会被初始化。
        现已改为分块幂等，保证任何部分缺失都能被单独补齐。
        """
        initialized_blocks = []

        # --- 鱼类模板 ---
        try:
            self._setup_fish_templates()
            initialized_blocks.append("fish")
        except Exception as e:
            logger.error(f"初始化鱼类模板失败（可能是表不存在，将继续其他块）: {e}")

        # --- 鱼饵模板 ---
        try:
            existing_bait_names = {b.name for b in (self.item_template_repo.get_all_baits() or [])}
            for bait in BAIT_DATA:
                if bait[0] not in existing_bait_names:
                    try:
                        self.item_template_repo.add_bait_template({
                            "name": bait[0],
                            "description": bait[1],
                            "rarity": bait[2],
                            "effect_description": bait[3],
                            "duration_minutes": bait[4],
                            "cost": bait[5],
                            "required_rod_rarity": bait[6]
                        })
                        existing_bait_names.add(bait[0])
                    except Exception as e:
                        logger.error(f"添加鱼饵失败 ({bait[0]}): {e}")
            initialized_blocks.append("baits")
        except Exception as e:
            logger.error(f"初始化鱼饵模板失败: {e}")

        # --- 鱼竿模板 ---
        try:
            existing_rod_names = {r.name for r in (self.item_template_repo.get_all_rods() or [])}
            for rod in ROD_DATA:
                if rod[0] not in existing_rod_names:
                    try:
                        self.item_template_repo.add_rod_template({
                            "name": rod[0],
                            "description": rod[1],
                            "rarity": rod[2],
                            "source": rod[3],
                            "purchase_cost": rod[4],
                            "bonus_fish_quality_modifier": rod[5],
                            "bonus_fish_quantity_modifier": rod[6],
                            "bonus_rare_fish_chance": rod[7],
                            "durability": rod[8],
                            "icon_url": rod[9]
                        })
                        existing_rod_names.add(rod[0])
                    except Exception as e:
                        logger.error(f"添加鱼竿失败 ({rod[0]}): {e}")
            initialized_blocks.append("rods")
        except Exception as e:
            logger.error(f"初始化鱼竿模板失败: {e}")

        # --- 饰品模板 ---
        try:
            existing_acc_names = {a.name for a in (self.item_template_repo.get_all_accessories() or [])}
            for acc in ACCESSORY_DATA:
                if acc[0] not in existing_acc_names:
                    try:
                        self.item_template_repo.add_accessory_template({
                            "name": acc[0],
                            "description": acc[1],
                            "rarity": acc[2],
                            "slot_type": acc[3],
                            "bonus_fish_quality_modifier": acc[4],
                            "bonus_fish_quantity_modifier": acc[5],
                            "bonus_rare_fish_chance": acc[6],
                            "bonus_coin_modifier": acc[7],
                            "other_bonus_description": acc[8],
                            "icon_url": acc[9]
                        })
                        existing_acc_names.add(acc[0])
                    except Exception as e:
                        logger.error(f"添加饰品失败 ({acc[0]}): {e}")
            initialized_blocks.append("accessories")
        except Exception as e:
            logger.error(f"初始化饰品模板失败: {e}")

        # --- 称号模板 ---
        # 注意：迁移 034 已预置了部分成就称号，因此不能简单按「表是否为空」判断，
        # 必须按 title_id 逐个补齐，否则 TITLE_DATA 中的称号永远不会被写入。
        try:
            if hasattr(self.item_template_repo, "add_title_template"):
                existing_title_ids = {
                    getattr(title, "title_id", None) for title in (self.item_template_repo.get_all_titles() or [])
                }
                added = 0
                for title in TITLE_DATA:
                    if title[0] in existing_title_ids:
                        continue
                    try:
                        self.item_template_repo.add_title_template({
                            "title_id": title[0],
                            "name": title[1],
                            "description": title[2],
                            "display_format": title[3]
                        })
                        existing_title_ids.add(title[0])
                        added += 1
                    except Exception as e:
                        logger.error(f"添加称号失败 (id={title[0]}, {title[1]}): {e}")
                if added:
                    initialized_blocks.append("titles")
        except Exception as e:
            logger.error(f"初始化称号模板失败: {e}")

        # --- 卡池池子 ---
        try:
            existing_pool_names = {
                pool["name"] for pool in (self.gacha_repo.get_all_pools() or [])
            }
            created_pools = []
            for pool in GACHA_POOL:
                if pool[1] in existing_pool_names:
                    continue
                self.gacha_repo.add_pool_template(
                    {
                        "pool_id": pool[0],
                        "name": pool[1],
                        "description": pool[2],
                        "cost_coins": pool[3],
                        "cost_premium_currency": pool[4],
                    }
                )
                existing_pool_names.add(pool[1])
                created_pools.append(pool[1])
            if created_pools:
                initialized_blocks.append("gacha_pools")
        except Exception as e:
            logger.error(f"初始化卡池失败: {e}")

        # --- 道具 ---
        try:
            self.create_initial_items()
        except Exception as e:
            logger.error(f"初始化道具失败: {e}")

        # --- 卡池物品（每个池独立幂等） ---
        try:
            self._setup_gacha_pool_items()
            initialized_blocks.append("gacha_pool_items")
        except Exception as e:
            logger.error(f"初始化卡池物品失败: {e}")

        # --- 商店与商品 ---
        try:
            self._setup_shops()
            initialized_blocks.append("shops")
        except Exception as e:
            logger.error(f"初始化商店失败: {e}")

        if initialized_blocks:
            logger.info(f"核心游戏数据初始化完成（本次初始化：{', '.join(initialized_blocks)}）。")
        else:
            logger.info("核心游戏数据已完整，跳过初始化。")

    def _setup_fish_templates(self):
        """填充鱼类模板（按名称去重，可重复调用）"""
        existing_names = {f.name for f in (self.item_template_repo.get_all_fish() or [])}
        for fish in FISH_DATA:
            if fish[0] in existing_names:
                continue
            try:
                self.item_template_repo.add_fish_template({
                    "name": fish[0],
                    "description": fish[1],
                    "rarity": fish[2],
                    "base_value": fish[3],
                    "min_weight": fish[4],
                    "max_weight": fish[5],
                    "icon_url": fish[6]
                })
                existing_names.add(fish[0])
            except Exception as e:
                logger.error(f"添加鱼类失败 ({fish[0]}): {e}")

    def _setup_gacha_pool_items(self):
        """按 GACHA_POOL_ITEMS 配置填充各卡池的物品与权重（每个池独立幂等）"""
        for pool_id, items in GACHA_POOL_ITEMS.items():
            # 已有物品的池子直接跳过，避免重复插入
            if self.gacha_repo.get_pool_items(pool_id):
                continue
            logger.info(f"正在初始化卡池 {pool_id} 的物品...")
            for item_type, item_id, quantity, weight in items:
                    # add_item_to_pool 要求 item_full_id 形如 "type-id"，
                    # 且内部会把 item_id 作为字符串写入（既有实现的约定，这里保持一致）
                    self.gacha_repo.add_item_to_pool(
                        pool_id,
                        {
                            "item_full_id": f"{item_type}-{item_id}",
                            "quantity": quantity,
                            "weight": weight,
                        },
                    )

    def _setup_shops(self):
        """确保商店与商品存在（幂等：按名称去重，不覆盖后台已改动的商品）"""
        if not self.shop_repo.get_all_shops():
            logger.info("正在初始化商店...")
            for shop_data in SHOP_DATA:
                self._create_shop_if_absent(shop_data)

        # 商品种子：逐个按名称判断，缺失才补
        self._ensure_default_shop_items()

        logger.info("商店数据初始化完成。")

    def _create_shop_if_absent(self, shop_data):
        """按商店名创建商店（已存在则跳过）"""
        try:
            all_shops = self.shop_repo.get_all_shops()
            if any(shop.get("name") == shop_data[1] for shop in all_shops):
                return False
            # SHOP_DATA 可选第 9、10 列为每日营业时段
            daily_start = shop_data[8] if len(shop_data) > 8 else None
            daily_end = shop_data[9] if len(shop_data) > 9 else None
            self.shop_repo.create_shop({
                "name": shop_data[1],
                "description": shop_data[2],
                "shop_type": shop_data[3],
                "is_active": shop_data[4],
                "start_time": shop_data[5],
                "end_time": shop_data[6],
                "daily_start_time": daily_start,
                "daily_end_time": daily_end,
                "sort_order": shop_data[7],
            })
            logger.info(f"创建商店: {shop_data[1]}")
            return True
        except Exception as e:
            logger.error(f"创建商店失败 ({shop_data[1]}): {e}")
            return False

    def _ensure_default_shop_items(self):
        """
        确保默认商品存在。

        * 商店1：按 SHOP_ITEM_DATA 中shop_id=1 的条目补齐；
          若种子配置中没有任何条目，则退化为「上架所有 3 星及以下鱼竿 + 所有有成本的鱼饵」。
        * 商店2 / 商店3：仅在对应 seed 条目存在时创建。
        * 全部按商品名称去重，后台手动添加/修改过的商品不会被覆盖。
        """
        if not self.shop_repo:
            return

        for entry in SHOP_ITEM_DATA:
            shop_id = entry.get("shop_id")
            item_name = entry.get("name")
            if not shop_id or not item_name:
                continue
            try:
                if self._shop_item_exists(shop_id, item_name):
                    continue
                self._create_shop_item_from_seed(shop_id, entry)
            except Exception as e:
                logger.error(f"创建商店商品失败 (shop={shop_id}, item={item_name}): {e}")

        # 兜底：若 SHOP_ITEM_DATA 未覆盖商店1 的鱼竿/鱼饵，仍按旧逻辑补齐
        if any(entry.get("shop_id") == 1 for entry in SHOP_ITEM_DATA):
            return
        self._ensure_shop1_default_items()

    def _shop_item_exists(self, shop_id: int, item_name: str) -> bool:
        """判断某商店下是否已存在同名商品"""
        try:
            existing_items = self.shop_repo.get_shop_items(shop_id)
            return any(item.get("name") == item_name for item in existing_items)
        except Exception:
            # 查询失败时不阻断初始化，交由 create_shop_item 的唯一性判断兜底
            return False

    def _create_shop_item_from_seed(self, shop_id: int, entry):
        """根据 SHOP_ITEM_DATA 条目创建商品及其成本/奖励"""
        costs = entry.get("costs") or []
        rewards = entry.get("rewards") or []
        if not rewards:
            logger.warning(f"商品 {entry.get('name')} 未配置奖励，已跳过创建。")
            return None

        item_data = {
            "name": entry.get("name"),
            "description": entry.get("description", ""),
            "category": entry.get("category", "general"),
            "is_active": entry.get("is_active", True),
            "sort_order": entry.get("sort_order", 100),
            "stock_total": entry.get("stock_total"),
            "per_user_limit": entry.get("per_user_limit"),
            "per_user_daily_limit": entry.get("per_user_daily_limit"),
        }
        created_item = self.shop_repo.create_shop_item(shop_id, item_data)
        item_id = created_item["item_id"]

        # 成本：兼容 (type, amount, item_id) 与 (type, amount, item_id, relation, group) 两种写法
        for cost in costs:
            cost_type = cost[0]
            cost_amount = cost[1]
            cost_item_id = cost[2] if len(cost) > 2 else None
            cost_relation = cost[3] if len(cost) > 3 else "and"
            group_id = cost[4] if len(cost) > 4 else None
            if cost_amount is None or cost_amount <= 0:
                logger.warning(f"商品 {item_data['name']} 的成本 {cost_type} 金额非法，已跳过该成本。")
                continue
            cost_data = {
                "cost_type": cost_type,
                "cost_amount": cost_amount,
                "cost_relation": cost_relation,
                "group_id": group_id,
            }
            if cost_item_id:
                cost_data["cost_item_id"] = cost_item_id
            # 鱼类成本支持品质（可选第 6 列）
            quality_level = cost[5] if len(cost) > 5 else None
            if quality_level is not None:
                cost_data["quality_level"] = quality_level
            self.shop_repo.add_item_cost(item_id, cost_data)

        # 奖励：兼容 (type, item_id, quantity) 与 (type, item_id, quantity, refine_level, quality_level)
        for reward in rewards:
            reward_type = reward[0]
            reward_item_id = reward[1] if len(reward) > 1 else None
            reward_quantity = reward[2] if len(reward) > 2 else 1
            reward_refine_level = reward[3] if len(reward) > 3 else None
            reward_quality_level = reward[4] if len(reward) > 4 else 0
            if reward_quantity is None or reward_quantity <= 0:
                logger.warning(f"商品 {item_data['name']} 的奖励 {reward_type} 数量非法，已跳过该奖励。")
                continue
            reward_data = {
                "reward_type": reward_type,
                "reward_quantity": reward_quantity,
                "reward_refine_level": reward_refine_level,
                "quality_level": reward_quality_level,
            }
            if reward_item_id:
                reward_data["reward_item_id"] = reward_item_id
            self.shop_repo.add_item_reward(item_id, reward_data)

        logger.info(f"已上架商品: {item_data['name']} (shop={shop_id})")
        return created_item

    def sync_shops_from_initial_data(self):
        """
        手动从 initial_data.py 同步商店和基础商品到数据库。
        这是一个幂等操作，可以安全地多次调用。
        """
        logger.info("正在从 initial_data.py 同步商店...")

        # 先确保基础数据已初始化（补齐模板 / 道具 / 卡池 / 商店）
        self.setup_initial_data()

        # 补齐缺失的商店（按名称去重，不覆盖后台改动）
        for shop_data in SHOP_DATA:
            self._create_shop_if_absent(shop_data)

        # 补齐缺失的商品（按名称去重，不覆盖后台改动）
        self._ensure_default_shop_items()

        logger.info("商店数据同步完成。")

    def _ensure_shop1_default_items(self):
        """确保商店1有默认商品（新设计：直接创建shop_items）"""
        logger.info("正在确保商店1有默认商品...")
        
        # 获取商店1的现有商品
        shop1_items = self.shop_repo.get_shop_items(1)
        existing_item_names = {item["name"] for item in shop1_items}

        # 添加所有3星以下的鱼竿到商店1
        rod_items = []
        for rod_data in ROD_DATA:
            if rod_data[2] <= 3 and rod_data[3] == "shop" and rod_data[4] and rod_data[4] > 0:  # rarity <= 3, source=shop, has cost
                rod_items.append(rod_data)
        
        for rod_data in rod_items:
            rod_name = rod_data[0]
            rod_id = ROD_DATA.index(rod_data) + 1
            
            # 检查是否已存在同名商品
            if rod_name in existing_item_names:
                logger.info(f"鱼竿商品已存在: {rod_name}")
                continue
            
            # 创建新商品
            rod_description = rod_data[1] if len(rod_data) > 1 else ""
            logger.info(f"创建鱼竿商品: {rod_name}, 描述: {rod_description}")
            
            # 创建商品
            item_data = {
                "name": rod_name,
                "description": rod_description,
                "category": "basic",
                "is_active": True,
                "sort_order": rod_data[2] * 10,  # 按稀有度排序
            }
            created_item = self.shop_repo.create_shop_item(1, item_data)
            item_id = created_item["item_id"]
            
            # 添加成本
            self.shop_repo.add_item_cost(item_id, {
                "cost_type": "coins",
                "cost_amount": rod_data[4],
                "cost_relation": "and",
            })
            
            # 添加奖励
            self.shop_repo.add_item_reward(item_id, {
                "reward_type": "rod",
                "reward_item_id": rod_id,
                "reward_quantity": 1,
                "reward_refine_level": 1,
            })
            
            logger.info(f"已上架鱼竿: {rod_name}")

        # 添加所有有成本的鱼饵到商店1
        bait_items = []
        for bait_data in BAIT_DATA:
            if bait_data[5] > 0:  # has cost > 0
                bait_items.append(bait_data)
        
        for bait_data in bait_items:
            bait_name = bait_data[0]
            bait_id = BAIT_DATA.index(bait_data) + 1
            
            # 检查是否已存在同名商品
            if bait_name in existing_item_names:
                logger.info(f"鱼饵商品已存在: {bait_name}")
                continue
            
            # 创建新商品
            bait_description = bait_data[1] if len(bait_data) > 1 else ""
            logger.info(f"创建鱼饵商品: {bait_name}, 描述: {bait_description}")
            
            # 创建商品
            item_data = {
                "name": bait_name,
                "description": bait_description,
                "category": "basic",
                "is_active": True,
                "sort_order": bait_data[2] * 10 + 100,  # 鱼饵排在鱼竿后面
            }
            created_item = self.shop_repo.create_shop_item(1, item_data)
            item_id = created_item["item_id"]
            
            # 添加成本
            self.shop_repo.add_item_cost(item_id, {
                "cost_type": "coins",
                "cost_amount": bait_data[5],
                "cost_relation": "and",
            })
            
            # 添加奖励
            self.shop_repo.add_item_reward(item_id, {
                "reward_type": "bait",
                "reward_item_id": bait_id,
                "reward_quantity": 1,
                "reward_refine_level": 1,
            })
            
            logger.info(f"已上架鱼饵: {bait_name}")

    def sync_all_initial_data(self):
        """
        手动从 initial_data.py 同步所有设计为可同步的数据（如道具、商店）。
        """
        logger.info("--- 开始同步所有初始设定 ---")
        self.create_initial_items()
        self.sync_shops_from_initial_data()
        logger.info("--- 所有初始设定同步完成 ---")

    def create_initial_items(self):
        """创建初始的道具"""
        existing_items = self.item_template_repo.get_all()
        existing_item_names = {item.name for item in existing_items}

        items_to_create = []
        for item_data in ITEM_DATA:
            if item_data[1] not in existing_item_names:
                items_to_create.append(
                    Item(
                        item_id=0,  # ID is auto-incrementing
                        name=item_data[1],
                        description=item_data[2],
                        rarity=item_data[3],
                        effect_description=item_data[4],
                        cost=item_data[5],
                        is_consumable=item_data[6],
                        icon_url=item_data[7],
                        effect_type=item_data[8],
                        effect_payload=item_data[9],
                    )
                )

        if items_to_create:
            logger.info(f"发现 {len(items_to_create)} 个新的道具，正在添加到数据库...")
            for item in items_to_create:
                self.item_template_repo.add(item)
            logger.info("新道具添加完成。")
        else:
            logger.info("没有发现新的道具需要添加。")

