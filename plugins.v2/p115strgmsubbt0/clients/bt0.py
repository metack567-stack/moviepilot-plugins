"""
bt0 磁力搜索客户端
调用本地 2bt0-hub（resource-hub）API 搜索磁力资源，作为 115 网盘搜索的兜底源
"""
import time

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

    def _get(self, url: str, params: dict):
        """GET 请求，带 2 次重试（本地服务偶发重启/繁忙时避免漏搜）"""
        last_exc = None
        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, timeout=self._timeout)
                resp.raise_for_status()
                return resp
            except Exception as e:
                last_exc = e
                logger.warning(f"bt0 请求失败（第 {attempt + 1}/3 次）：{e}")
                if attempt < 2:
                    time.sleep(0.5)
        raise last_exc

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
            resp = self._get(
                f"{self._base_url}/api/items",
                {"source": "local", "q": keyword, "sc": sc, "page": page}
            )
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
            resp = self._get(
                f"{self._base_url}/api/resolve",
                {"q": keyword, "year": year}
            )
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

    # ---- 剧集信息解析（供电视剧精准匹配使用）----
    _EP_FULL_RE = __import__("re").compile(r"[\[\【]\s*全\s*(\d+)\s*集\s*[\]\】]")
    _EP_RANGE_RE = __import__("re").compile(r"[\[\【]\s*第\s*(\d{1,4})\s*(?:[-~到]\s*(\d{1,4}))?\s*集\s*[\]\】]")
    _EP_SE_RE = __import__("re").compile(r"[S＄](\d{1,2})\s*[EＥ](\d{1,3})(?:\s*[-~]\s*[EＥ]?(\d{1,3}))?", __import__("re").IGNORECASE)
    _EP_E_RE = __import__("re").compile(r"(?<![A-Za-z0-9])[EＥ](\d{1,3})(?![A-Za-z0-9])")

    @staticmethod
    def parse_episodes(title: str, movie_episodes: str = "") -> List[int]:
        """从磁力标题解析覆盖集数（按优先级）：

        1) [全N集] -> 1..N；2) [第X-Y集] -> X..Y；3) [第N集] -> N；
        4) SxxEyy 或 SxxEyy-Ezz -> 季内集号；5) Eyy -> 集号。
        以上都没有时，才用影片总集数（movie_episodes）兜底——避免欧美剧单集磁力
        （如 S01E03）被错误当作全集参与择优；都拿不到返回空列表。
        """
        if title:
            m = BTOClient._EP_FULL_RE.search(title)
            if m:
                n = int(m.group(1))
                return list(range(1, n + 1)) if n > 0 else []
            m = BTOClient._EP_RANGE_RE.search(title)
            if m:
                a = int(m.group(1))
                b = int(m.group(2)) if m.group(2) else a
                if 0 < a <= b:
                    return list(range(a, b + 1))
                return []
            m = BTOClient._EP_SE_RE.search(title)
            if m:
                a = int(m.group(2))
                b = int(m.group(3)) if m.group(3) else a
                if 0 < a <= b:
                    return list(range(a, b + 1))
                return []
            m = BTOClient._EP_E_RE.search(title)
            if m:
                n = int(m.group(1))
                return [n] if n > 0 else []
        if movie_episodes:
            try:
                n = int(str(movie_episodes).strip())
                if n > 0:
                    return list(range(1, n + 1))
            except (TypeError, ValueError):
                pass
        return []


