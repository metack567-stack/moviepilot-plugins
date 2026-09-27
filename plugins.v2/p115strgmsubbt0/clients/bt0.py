"""
bt0 磁力搜索客户端
调用本地 2bt0-hub（resource-hub）API 搜索磁力资源，作为 115 网盘搜索的兜底源
"""
import requests
from typing import List, Dict

from app.log import logger


class BTOClient:
    """bt0 磁力库搜索客户端"""

    def __init__(self, base_url: str = "http://192.168.8.219:8000", timeout: int = 10, section: int = 1):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        # 1=电影 2=电视剧（对应 2bt0-hub 板块）
        self._section = section

    def search(self, keyword: str, page: int = 1, section: int = None) -> List[Dict]:
        """
        搜索磁力资源

        :param keyword: 搜索关键词
        :param page: 页码
        :param section: 板块 1=电影 2=电视剧（不传用默认）
        :return: 磁力条目列表 [{id, title, magnet, size, published_at, category, detail_url}]
        """
        try:
            sc = section if section is not None else self._section
            resp = requests.get(
                f"{self._base_url}/api/items",
                params={"source": "local", "q": keyword, "sc": sc, "page": page},
                timeout=self._timeout
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items") or []
            logger.info(f"bt0 搜索 '{keyword}' 返回 {len(items)} 条")
            return items
        except Exception as e:
            logger.error(f"bt0 搜索失败: {e}")
            return []
    def resolve(self, keyword: str, year: str = "") -> Dict:
        """
        精确匹配：按标题+年份解析影片，返回该影片全部磁力

        调用 2bt0-hub /api/resolve（movies 表 title/otitle/alias + years 匹配
        -> movies.idcode -> magnets.movie_id），避免同名/同系列错配。

        :param keyword: 影片标题
        :param year: 年份（可空）
        :return: {"matched": bool, "movie": {...}|None, "magnets": [...]}
        """
        try:
            resp = requests.get(
                f"{self._base_url}/api/resolve",
                params={"q": keyword, "year": year},
                timeout=self._timeout
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"bt0 resolve 失败: {e}")
            return {"matched": False, "movie": None, "magnets": []}

    # ---- 标题匹配工具（借鉴自 pansou 客户端，用于降级路径的标题校验/排序）----
    _PUNCT_GAP_RE = __import__("re").compile(r"[\s\u3000:：·•.,，。!！?？（）【】\[\]/／\\＼-]+")

    @staticmethod
    def _normalize_for_match(text: str) -> str:
        """统一空白、NFKC 与常见全角标点，便于判断关键词是否出现在标题中"""
        import unicodedata
        if not text:
            return ""
        t = unicodedata.normalize("NFKC", text)
        for old, new in (
            ("：", ":"), ("，", ","), ("（", "("), ("）", ")"),
            ("【", "["), ("】", "]"), ("！", "!"), ("？", "?"),
            ("–", "-"), ("—", "-"), ("…", "..."),
        ):
            t = t.replace(old, new)
        t = __import__("re").sub(r"[\s\u3000]+", " ", t).strip()
        return t.casefold()

    @classmethod
    def _compact_for_match(cls, text: str) -> str:
        """在规范化基础上去掉标点与空白，使全角/半角标点差异可忽略"""
        base = cls._normalize_for_match(text)
        return cls._PUNCT_GAP_RE.sub("", base)

    @classmethod
    def _title_matches_search_key(cls, key: str, title: str) -> bool:
        """判断标题是否包含搜索关键词：原串子串 -> 规范化子串 -> 紧凑子串（短关键词不用紧凑路径）"""
        if not key:
            return True
        t = title or ""
        if key in t:
            return True
        nk = cls._normalize_for_match(key)
        nt = cls._normalize_for_match(t)
        if nk and nk in nt:
            return True
        ck = cls._compact_for_match(key)
        ct = cls._compact_for_match(t)
        if len(ck) < 2:
            return False
        return ck in ct

