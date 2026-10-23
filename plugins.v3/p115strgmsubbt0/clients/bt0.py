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

    def __init__(self, base_url: str = "http://192.168.8.219:8000", timeout: int = 10, section: int = 1, api_key: str = ""):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        # 1=电影 2=电视剧（对应 2bt0-hub 板块）
        self._section = section
        # 2bt0 对外 API 密钥（X-API-Key 头；bt0 服务已强制鉴权，缺失 401）
        self._api_key = (api_key or "").strip()

    def _get(self, url: str, params: dict):
        """GET 请求，带 2 次重试（本地服务偶发重启/繁忙时避免漏搜）"""
        headers = {"X-API-Key": self._api_key} if self._api_key else {}
        last_exc = None
        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=self._timeout)
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
    def _local_items(self, params: dict, max_pages: int = 3) -> List[Dict]:
        """调用 2bt0-hub 本地库接口（新版 /api/items，source=local）并翻页汇总"""
        out: List[Dict] = []
        page = 1
        while page <= max_pages:
            p = dict(params)
            p.update({"source": "local", "page": page})
            resp = self._get(f"{self._base_url}/api/items", p)
            data = resp.json() or {}
            batch = data.get("items") or []
            out.extend(batch)
            total_pages = int(data.get("total_pages") or 1)
            if not batch or page >= min(total_pages, max_pages):
                break
            page += 1
        return out

    def _movie_detail(self, idcode: str) -> Dict:
        """取影片详情（含 years / episodes），用于精确匹配校验"""
        try:
            resp = self._get(f"{self._base_url}/api/movie/{idcode}", {})
            return ((resp.json() or {}).get("movie")) or {}
        except Exception as e:
            logger.warning(f"bt0 影片详情获取失败（{idcode}）：{e}")
            return {}

    def _movie_magnets(self, movie_id: str) -> List[Dict]:
        """按影片取磁力（对外 API /api/magnets）：一次调用返回该片全部磁力。

        2bt0 对外 API 强制 X-API-Key 鉴权；page 参数被忽略（一次返回全量，含 total）。
        返回字段：[{info_hash, magnet, title, size, published_at, category, detail_url, quality}]。
        """
        try:
            resp = self._get(
                f"{self._base_url}/api/magnets",
                {"movie_id": str(movie_id)}
            )
            data = resp.json() or {}
            magnets = data.get("magnets") or []
            logger.info(
                f"bt0 /api/magnets movie_id={movie_id} -> {len(magnets)}/{data.get('total')} 条磁力"
            )
            return magnets
        except Exception as e:
            logger.error(f"bt0 /api/magnets 失败（{movie_id}）：{e}")
            return []

    def resolve(self, keyword: str, year: str = "") -> Dict:
        """
        精确匹配：按标题+年份解析影片，返回该影片全部磁力

        新版 2bt0-hub 已移除 /api/resolve（该接口原为本地补丁），改为组合使用
        通用接口：/api/items?source=local&q=<标题> 找候选影片
        -> /api/movie/{idcode} 校验标题/年份 -> /api/items?source=local&movie_id=<idcode> 取全部磁力。
        未命中返回 matched=False，调用方降级模糊搜索。

        :param keyword: 影片标题
        :param year: 年份（可空）
        :return: {"matched": bool, "movie": {...}|None, "magnets": [...]}
        """
        kw = (keyword or "").strip()
        if not kw:
            return {"matched": False, "movie": None, "magnets": []}
        try:
            items = self._local_items({"q": kw, "sc": self._section}, max_pages=3)
            groups: Dict[str, Dict] = {}
            for it in items:
                extra = it.get("extra") or {}
                if not isinstance(extra, dict):
                    continue
                mid = str(extra.get("movie_id") or "")
                if not mid:
                    continue
                g = groups.setdefault(mid, {"title": extra.get("movie_title") or "", "magnets": []})
                g["magnets"].append(it)
            if not groups:
                return {"matched": False, "movie": None, "magnets": []}

            nk, ck = self._normalize_for_match(kw), self._compact_for_match(kw)
            cands = []
            for mid, g in groups.items():
                title = g["title"] or ""
                if not title:
                    continue
                if self._normalize_for_match(title) == nk or self._compact_for_match(title) == ck:
                    score = 3
                elif self._title_matches_search_key(kw, title) or self._title_matches_search_key(title, kw):
                    score = 2
                else:
                    continue
                cands.append((score, mid, g))
            if not cands:
                return {"matched": False, "movie": None, "magnets": []}
            cands.sort(key=lambda x: (-x[0], x[1]))

            y = (year or "").strip()
            for _score, mid, g in cands[:3]:
                movie = self._movie_detail(mid) or {"idcode": mid, "title": g["title"]}
                if y:
                    my = str(movie.get("years") or "").strip()
                    if not (my == y or my.startswith(y)):
                        continue
                magnets = self._movie_magnets(mid) or g["magnets"]
                logger.info(
                    f"bt0 精确匹配（本地库）：{movie.get('title')}（{movie.get('years')}）"
                    f"-> {len(magnets)} 条磁力"
                )
                return {"matched": True, "movie": movie, "magnets": magnets}
            return {"matched": False, "movie": None, "magnets": []}
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


