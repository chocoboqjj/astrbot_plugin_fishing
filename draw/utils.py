import os
import hashlib
from typing import Optional, Any
from PIL import Image, ImageDraw
from astrbot.api import logger

async def get_user_avatar(user_id: str, data_dir: str, avatar_size: int = 50, event: Any = None) -> Optional[Image.Image]:
    """
    获取用户头像并处理为圆形

    Args:
        user_id: 用户ID
        data_dir: 插件的数据目录
        avatar_size: 头像尺寸
        event: 可选，触发该渲染的消息事件。官方 Bot(qq_official) 下 user_id 为 openid（非 QQ 号），
               无法用 qlogo 拉头像；传入 event 时会尝试调官方接口按 openid 取头像 URL。
               其它平台或不需要官方头像时传 None 即可（仅 QQ 号用户能显示头像）。

    Returns:
        处理后的头像图像，如果失败返回None
    """
    try:
        import aiohttp
        from io import BytesIO
        import time

        # 创建头像缓存目录
        cache_dir = os.path.join(data_dir, "avatar_cache")
        os.makedirs(cache_dir, exist_ok=True)

        # 安全化user_id用于文件名
        import re
        safe_user_id = re.sub(r'[^a-zA-Z0-9._-]', '_', user_id)
        safe_user_id = re.sub(r'_+', '_', safe_user_id).strip('_') or 'unknown'
        avatar_cache_path = os.path.join(cache_dir, f"{safe_user_id}_avatar.png")

        # 检查是否有缓存的头像（24小时刷新）
        avatar_image = None
        if os.path.exists(avatar_cache_path):
            try:
                file_age = time.time() - os.path.getmtime(avatar_cache_path)
                if file_age < 86400:  # 24小时
                    avatar_image = Image.open(avatar_cache_path).convert('RGBA')
            except:
                pass

        # 如果没有缓存或缓存过期，重新下载
        if avatar_image is None:
            is_qq = user_id.isdigit() and (5 <= len(user_id) <= 12)
            avatar_url = None
            if is_qq:
                # NapCat / 纯数字 QQ 号：直接走 qlogo
                avatar_url = f"https://q4.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640"
            elif event is not None:
                # 官方 Bot(openid) 等：尝试用官方接口按 openid 取头像 URL
                avatar_url = await _resolve_official_avatar(event)
            if not avatar_url:
                logger.debug(f"user_id={user_id} 无法解析头像来源，跳过头像拉取。")
                return None
            try:
                # 增加超时时间
                timeout = aiohttp.ClientTimeout(total=10, connect=5)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(avatar_url) as response:
                        if response.status == 200:
                            content = await response.read()
                            avatar_image = Image.open(BytesIO(content)).convert('RGBA')
                            # 保存到缓存
                            avatar_image.save(avatar_cache_path, 'PNG')
                        else:
                            logger.debug(f"头像下载失败，HTTP {response.status}: {avatar_url}")
                            return None
            except Exception as e:
                # QQ 号场景的网络异常值得关注；openid 解析失败的兜底已降级为 debug
                if is_qq:
                    logger.warning(f"头像下载失败: {e}")
                else:
                    logger.debug(f"头像下载失败: {e}")
                return None

        if avatar_image:
            return avatar_postprocess(avatar_image, avatar_size)

    except Exception as e:
        pass

    return None


async def _resolve_official_avatar(event: Any) -> Optional[str]:
    """官方 Bot(qq_official) 下，依 openid 调官方接口取用户头像 URL。

    改用 core.qq_official 多信号容错提取 openid（兼容 dict / 包装对象 / 不同 AstrBot
    版本形态），不再要求 raw_message 必须是 botpy 原生 GroupMessage / C2CMessage
    （用户实测下该 isinstance 判定为 False，导致头像始终拉取失败）。

    群聊与单聊用不同接口：
      - 群消息：member openid 是「群作用域」的，必须用
        ``GET /v2/groups/{group_openid}/members/{member_openid}``（用 C2C 的
        ``/v2/users/{openid}`` 会 404）。这是头像此前在群聊里一直拉不到的根因。
      - 单聊：用 ``GET /v2/users/{openid}``。
    两个接口返回结构一致（含 avatar 字段），由 ``_extract_avatar_from_userinfo`` 解析。
    缺少 bot 客户端、openid、或任何失败均返回 None，由调用方静默跳过（不显示头像）。
    """
    try:
        from botpy.http import Route
    except Exception:
        return None

    bot = getattr(event, "bot", None)
    if bot is None or getattr(bot, "api", None) is None:
        return None
    raw = getattr(getattr(event, "message_obj", None), "raw_message", None)

    from ..core.qq_official import get_sender_openid, get_group_openid

    # openid 来源：优先从 raw_message 取；官方 Bot 下 event.get_sender_id() 返回的也是 openid，
    # 作为更可靠的兜底（raw_message 结构因 AstrBot 版本而异，未必暴露 author.user_openid）。
    openid = (get_sender_openid(raw) if raw is not None else None)
    if not openid and hasattr(event, "get_sender_id"):
        try:
            sid = event.get_sender_id()
            if sid:
                openid = sid
        except Exception:
            pass
    group_openid = get_group_openid(raw) if raw is not None else None

    if not openid:
        logger.debug(
            f"[头像] 官方Bot取头像URL跳过：raw_message 类型 "
            f"{type(raw).__name__ if raw is not None else 'None'}，"
            f"且 event.get_sender_id() 也为空；raw_repr={repr(raw)[:300]}"
        )
        return None

    # 候选路由：群聊优先用成员接口，单聊用用户接口；两者都试一遍以提高成功率。
    routes: list = []
    if group_openid:
        routes.append(("group_member", Route("GET", "/v2/groups/{group_openid}/members/{member_openid}", group_openid=group_openid, member_openid=openid)))
    routes.append(("c2c_user", Route("GET", "/v2/users/{openid}", openid=openid)))

    last_err: Optional[str] = None
    for label, route in routes:
        try:
            data = await bot.api._http.request(route)
            url = _extract_avatar_from_userinfo(data)
            if url:
                logger.debug(f"[头像] 官方Bot取头像URL成功：route={label} openid={openid} url={url[:80]}")
                return url
            logger.debug(
                f"[头像] 官方Bot取头像URL：route={label} openid={openid} "
                f"接口已返回但未解析到 avatar，raw={repr(data)[:300]}"
            )
            last_err = "no_avatar_field"
        except Exception as e:
            last_err = f"{e}"
            logger.debug(f"[头像] 官方Bot取头像URL失败：route={label} openid={openid} 错误={e}")
    return None


def _extract_avatar_from_userinfo(data: Any) -> Optional[str]:
    """从官方接口返回的用户/成员资料中稳健提取 avatar 字段（兼容不同返回结构）。"""
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("avatar"), str) and data["avatar"]:
        return data["avatar"]
    user = data.get("user")
    if isinstance(user, dict) and isinstance(user.get("avatar"), str) and user["avatar"]:
        return user["avatar"]
    inner = data.get("data")
    if isinstance(inner, dict):
        if isinstance(inner.get("avatar"), str) and inner["avatar"]:
            return inner["avatar"]
        u = inner.get("user")
        if isinstance(u, dict) and isinstance(u.get("avatar"), str) and u["avatar"]:
            return u["avatar"]
    return None

def avatar_postprocess(avatar_image: Image.Image, size: int) -> Image.Image:
    """
    将头像处理为指定大小的圆角头像
    """
    # 调整头像大小
    avatar_image = avatar_image.resize((size, size), Image.Resampling.LANCZOS)
    
    # 使用更合适的圆角半径
    corner_radius = size // 8  # 稍微减小圆角，看起来更自然
    
    # 抗锯齿处理
    scale_factor = 4
    large_size = size * scale_factor
    large_radius = corner_radius * scale_factor
    
    # 创建高质量遮罩
    large_mask = Image.new('L', (large_size, large_size), 0)
    large_draw = ImageDraw.Draw(large_mask)
    
    # 绘制圆角矩形
    large_draw.rounded_rectangle(
        [0, 0, large_size, large_size], 
        radius=large_radius, 
        fill=255
    )
    
    # 高质量缩放
    mask = large_mask.resize((size, size), Image.Resampling.LANCZOS)
    avatar_image.putalpha(mask)
    
    return avatar_image

async def get_fish_icon(icon_url: str, data_dir: str, icon_size: int = 60) -> Optional[Image.Image]:
    """
    下载并处理鱼类图标
    
    Args:
        icon_url: 图标URL
        data_dir: 插件的数据目录
        icon_size: 图标尺寸
    
    Returns:
        处理后的图标图像，如果失败返回None
    """
    if not icon_url or not icon_url.strip():
        return None
    
    try:
        import aiohttp
        from io import BytesIO
        import time
        
        # 创建图标缓存目录
        cache_dir = os.path.join(data_dir, "fish_icon_cache")
        os.makedirs(cache_dir, exist_ok=True)
        
        # 使用URL的hash作为缓存文件名
        url_hash = hashlib.md5(icon_url.encode()).hexdigest()
        icon_cache_path = os.path.join(cache_dir, f"{url_hash}.png")
        
        # 检查是否有缓存的图标（7天刷新）
        icon_image = None
        if os.path.exists(icon_cache_path):
            try:
                file_age = time.time() - os.path.getmtime(icon_cache_path)
                if file_age < 604800:  # 7天
                    icon_image = Image.open(icon_cache_path).convert('RGBA')
            except:
                pass
        
        # 如果没有缓存或缓存过期，重新下载
        if icon_image is None:
            try:
                timeout = aiohttp.ClientTimeout(total=10, connect=5)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(icon_url.strip()) as response:
                        if response.status == 200:
                            content = await response.read()
                            # 限制文件大小（最大5MB）
                            if len(content) > 5 * 1024 * 1024:
                                logger.warning(f"图标文件过大，跳过: {icon_url}")
                                return None
                            icon_image = Image.open(BytesIO(content)).convert('RGBA')
                            # 保存到缓存
                            icon_image.save(icon_cache_path, 'PNG')
                        else:
                            logger.warning(f"下载图标失败，HTTP状态码: {response.status}, URL: {icon_url}")
                            return None
            except Exception as e:
                # 如果下载失败，记录日志但不抛出异常
                logger.warning(f"图标下载失败: {e}, URL: {icon_url}")
                return None
        
        if icon_image:
            # 调整图标大小并保持宽高比
            icon_image.thumbnail((icon_size, icon_size), Image.Resampling.LANCZOS)
            return icon_image
        
    except Exception as e:
        logger.warning(f"处理图标时发生错误: {e}, URL: {icon_url}")
    
    return None
