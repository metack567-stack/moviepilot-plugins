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
