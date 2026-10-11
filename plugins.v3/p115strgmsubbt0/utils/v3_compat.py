"""
MoviePilot V3 兼容层

MP V3 重构了 Subscribe 模型：不再有 tmdbid / doubanid / modified 列，
改用 media_source（themoviedb/douban/bangumi/...） + media_id。
本模块提供兼容取法：V2 环境直接读老字段，V3 环境读 media_source/media_id。
"""
from typing import Any, List, Optional

__all__ = ["sub_tmdbid", "sub_doubanid", "subscribe_modified", "list_subs_by_tmdbid", "recognize_kwargs"]

_TMDB_SOURCES = {"themoviedb", "tmdb"}
_DOUBAN_SOURCES = {"douban"}


def _src(sub: Any) -> str:
    v = getattr(sub, "media_source", None)
    v = getattr(v, "value", v)          # 可能是 MediaSource 枚举
    return str(v or "").strip().lower()


def _mid(sub: Any) -> Optional[str]:
    v = getattr(sub, "media_id", None)
    return None if v in (None, "", 0) else str(v)


def sub_tmdbid(sub: Any) -> Optional[str]:
    """V2: subscribe.tmdbid；V3: media_source=='themoviedb' 时的 media_id。"""
    legacy = getattr(sub, "tmdbid", None)
    if legacy:
        return str(legacy)
    return _mid(sub) if _src(sub) in _TMDB_SOURCES else None


def sub_doubanid(sub: Any) -> Optional[str]:
    """V2: subscribe.doubanid；V3: media_source=='douban' 时的 media_id。"""
    legacy = getattr(sub, "doubanid", None)
    if legacy:
        return str(legacy)
    return _mid(sub) if _src(sub) in _DOUBAN_SOURCES else None


def subscribe_modified(sub: Any) -> Any:
    """V2: subscribe.modified；V3 用 last_update 代替。"""
    return getattr(sub, "modified", None) or getattr(sub, "last_update", None)


def list_subs_by_tmdbid(tmdbid: Any, season: Optional[int] = None) -> List[Any]:
    """替代 V3 已移除的 SubscribeOper().list_by_tmdbid(tmdbid, season)。"""
    from app.db.subscribe_oper import SubscribeOper
    target = str(tmdbid)
    out: List[Any] = []
    for s in (SubscribeOper().list() or []):
        if sub_tmdbid(s) != target:
            continue
        if season is not None and (getattr(s, "season", None) or 1) != (season or 1):
            continue
        out.append(s)
    return out


def _supports_media_id() -> bool:
    """V3 的 recognize_media 用 media_source+media_id；V2 用 tmdbid/doubanid。"""
    try:
        import inspect
        from app.chain.media import MediaChain
        return "media_id" in inspect.signature(MediaChain.recognize_media).parameters
    except Exception:
        return False


_V3_MEDIA_ID = _supports_media_id()


def recognize_kwargs(sub: Any = None, tmdbid: Any = None, doubanid: Any = None) -> dict:
    """给 recognize_media 用的兼容 kwargs：V3 → media_source+media_id，V2 → tmdbid/doubanid。"""
    if sub is not None:
        src, mid = _src(sub), _mid(sub)
        if src and mid:
            return {"media_source": src, "media_id": mid}
        tmdbid = tmdbid or getattr(sub, "tmdbid", None)
        doubanid = doubanid or getattr(sub, "doubanid", None)
    if tmdbid:
        if _V3_MEDIA_ID:
            return {"media_source": "themoviedb", "media_id": str(tmdbid)}
        return {"tmdbid": str(tmdbid)}
    if doubanid:
        if _V3_MEDIA_ID:
            return {"media_source": "douban", "media_id": str(doubanid)}
        return {"doubanid": str(doubanid)}
    return {}
