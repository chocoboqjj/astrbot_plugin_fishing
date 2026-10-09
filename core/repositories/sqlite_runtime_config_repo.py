import json
import sqlite3
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any

from astrbot.api import logger

from .abstract_repository import AbstractRuntimeConfigRepository


class SqliteRuntimeConfigRepository(AbstractRuntimeConfigRepository):
    """运营配置覆盖仓储的SQLite实现"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()

    def _get_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 30000")
            self._local.connection = conn
        return conn

    # ---- 读取 ----

    def get_all_overrides(self, active_only: bool = True) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM runtime_config"
        if active_only:
            sql += " WHERE is_active = TRUE"
        sql += " ORDER BY category ASC, config_key ASC"
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql)
                rows = cursor.fetchall()
                return [self._normalize(dict(row)) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"读取运营配置失败: {e}")
            return []

    def get_override(self, config_key: str) -> Optional[Dict[str, Any]]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM runtime_config WHERE config_key = ? AND is_active = TRUE",
                    (config_key,),
                )
                row = cursor.fetchone()
                return self._normalize(dict(row)) if row else None
        except sqlite3.Error as e:
            logger.error(f"读取运营配置 ({config_key}) 失败: {e}")
            return None

    # ---- 写入 ----

    def upsert_override(
        self,
        config_key: str,
        config_value: Optional[str],
        value_type: str = "string",
        category: Optional[str] = None,
        description: Optional[str] = None,
        updated_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        新增或更新配置覆盖。

        config_value 允许为空字符串或 None——表示「清除该覆盖，沿用默认值」，
        此时保留记录以便保留说明文字与操作痕迹。
        """
        if not config_key or not isinstance(config_key, str):
            raise ValueError("配置键不能为空")

        # 统一以 JSON 字符串存储，保证 int/float/bool/对象都能原样取回
        if config_value is None or config_value == "":
            stored_value = None
        else:
            try:
                json.loads(config_value)
                stored_value = config_value
            except (TypeError, ValueError):
                # 非 JSON 内容按原始字符串存储，读取时 ConfigService 会做类型修正
                stored_value = json.dumps(str(config_value))

        now = datetime.now()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO runtime_config
                    (config_key, config_value, value_type, category, description,
                     is_active, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?, TRUE, ?, ?)
                ON CONFLICT(config_key) DO UPDATE SET
                    config_value = excluded.config_value,
                    value_type = excluded.value_type,
                    category = COALESCE(excluded.category, runtime_config.category),
                    description = COALESCE(excluded.description, runtime_config.description),
                    is_active = TRUE,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (
                    config_key,
                    stored_value,
                    value_type,
                    category,
                    description,
                    updated_by or "system",
                    now,
                ),
            )
            conn.commit()
            cursor.execute(
                "SELECT * FROM runtime_config WHERE config_key = ?", (config_key,)
            )
            row = cursor.fetchone()
        return self._normalize(dict(row)) if row else {}

    def set_active(self, config_key: str, is_active: bool, updated_by: Optional[str] = None) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE runtime_config
                    SET is_active = ?, updated_by = ?, updated_at = ?
                    WHERE config_key = ?
                    """,
                    (1 if is_active else 0, updated_by or "system", datetime.now(), config_key),
                )
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"切换配置状态失败 ({config_key}): {e}")
            return False

    def delete_override(self, config_key: str) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM runtime_config WHERE config_key = ?", (config_key,))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"删除配置失败 ({config_key}): {e}")
            return False

    def reset_category(self, category: str) -> int:
        """清除某个配置块的全部覆盖值（保留记录，仅把值置空以沿用默认值）"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE runtime_config
                    SET config_value = NULL, is_active = TRUE,
                        updated_by = 'reset', updated_at = ?
                    WHERE category = ?
                    """,
                    (datetime.now(), category),
                )
                conn.commit()
                return cursor.rowcount
        except sqlite3.Error as e:
            logger.error(f"重置配置块失败 ({category}): {e}")
            return 0

    def reset_all(self) -> int:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE runtime_config
                    SET config_value = NULL, is_active = TRUE,
                        updated_by = 'reset', updated_at = ?
                    """,
                    (datetime.now(),),
                )
                conn.commit()
                return cursor.rowcount
        except sqlite3.Error as e:
            logger.error(f"重置全部配置失败: {e}")
            return 0

    # ---- 内部工具 ----

    def _normalize(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """把数据库行转为便于使用的字典，并把 config_value 解析为 Python 对象"""
        result = dict(row)
        raw = result.get("config_value")
        parsed: Any = None
        if raw is not None and raw != "":
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                parsed = raw
        result["parsed_value"] = parsed
        result["has_override"] = raw is not None and raw != ""
        if result.get("is_active") is not None:
            result["is_active"] = bool(result["is_active"])
        return result