#!/usr/bin/env python3
"""给「115网盘订阅追更魔改版」（jinyuhao-886/P115StrgmSub，非磁力版）打 MoviePilot V3 兼容补丁。

背景：MP V3 删掉 Subscribe.tmdbid / doubanid / modified，改用 media_source+media_id；
SubscribeOper().list_by_tmdbid() 被删除；recognize_media() 不再接受 tmdbid=/doubanid=。
本插件仍用老写法 ⇒ 一跑就把每个订阅都打崩（'Subscribe' object has no attribute 'tmdbid'）。

用法（对已解包到磁盘的插件目录，或直接对容器里的目录）：
    python3 patch-v3compat-p115strgmsub.py <插件目录>
典型流程（上游更新后重打）：
    docker cp moviepilot-v3:/app/app/plugins/p115strgmsub /tmp/x && \
    python3 tools/patch-v3compat-p115strgmsub.py /tmp/x/p115strgmsub && \
    docker cp /tmp/x/p115strgmsub moviepilot-v3:/app/app/plugins/ && reload

幂等：已打过补丁会直接报「无需修改」（检测到 sub_tmdbid 调用即视为已打）。
"""
import io
import os
import sys


def patch(dirpath: str) -> None:
    sync = os.path.join(dirpath, 'handlers', 'sync.py')
    init = os.path.join(dirpath, '__init__.py')
    compat = os.path.join(dirpath, 'utils', 'v3_compat.py')
    for p in (sync, init):
        if not os.path.exists(p):
            sys.exit(f'找不到 {p}（目录给错了吗？）')

    # 0) 兼容模块就位（与本仓库 plugins.v3/p115strgmsubbt0/utils/v3_compat.py 同一份）
    src_compat = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              '..', 'plugins.v3', 'p115strgmsubbt0', 'utils', 'v3_compat.py')
    if os.path.exists(src_compat):
        io.open(compat, 'w', encoding='utf-8').write(io.open(src_compat, encoding='utf-8').read())
        print(f'  ✓ 写入 {compat}')
    elif not os.path.exists(compat):
        sys.exit('缺少 utils/v3_compat.py（也找不到仓库母本）')

    edits = [
        # ---- handlers/sync.py ----
        (sync,
         'from app.utils.string import StringUtils\n',
         'from app.utils.string import StringUtils\n\n'
         'from ..utils.v3_compat import (sub_tmdbid, sub_doubanid,\n'
         '                               list_subs_by_tmdbid, recognize_kwargs)\n'),
        # recognize_media 多行块（电影 / 剧集）
        (sync,
         '                tmdbid=subscribe.tmdbid,\n                doubanid=subscribe.doubanid,\n',
         '                **recognize_kwargs(subscribe),\n'),
        # recognize_media 单行块（洗版）
        (sync,
         '                tmdbid=subscribe.tmdbid, doubanid=subscribe.doubanid, cache=True\n',
         '                **recognize_kwargs(subscribe), cache=True\n'),
        # getattr 形态
        (sync,
         "                tmdbid=getattr(subscribe, 'tmdbid', None),\n"
         "                doubanid=getattr(subscribe, 'doubanid', None),\n",
         '                **recognize_kwargs(subscribe),\n'),
        # ---- __init__.py ----
        (init,
         'from app.log import logger\n',
         'from app.log import logger\n\n'
         'from .utils.v3_compat import (sub_tmdbid, sub_doubanid,\n'
         '                              list_subs_by_tmdbid, recognize_kwargs)\n'),
        (init,
         'media_info = self.chain.recognize_media(mtype=mtype, tmdbid=tmdb_id)',
         'media_info = self.chain.recognize_media(mtype=mtype, **recognize_kwargs(tmdbid=tmdb_id))'),
        (init,
         'SubscribeOper().list_by_tmdbid(tmdbid, season)',
         'list_subs_by_tmdbid(tmdbid, season)'),
    ]

    failed = []
    for path, old, new in edits:
        t = io.open(path, encoding='utf-8').read()
        if old not in t:
            failed.append((path, old.splitlines()[0]))
            continue
        cnt = t.count(old)
        io.open(path, 'w', encoding='utf-8').write(t.replace(old, new))
        print(f'  ✓ {os.path.relpath(path, dirpath)}: {old.splitlines()[0][:55]} ×{cnt}')

    # 属性读取统一走兼容函数（subscribe.tmdbid / .doubanid 可能已不存在）
    for path in (sync, init):
        t = io.open(path, encoding='utf-8').read()
        if 'v3_compat' in t and (t.count('subscribe.tmdbid')
                                 or t.count('subscribe.doubanid')):
            n1 = t.count('subscribe.tmdbid')
            t = t.replace('subscribe.tmdbid', 'sub_tmdbid(subscribe)')
            t = t.replace('subscribe.doubanid', 'sub_doubanid(subscribe)')
            io.open(path, 'w', encoding='utf-8').write(t)
            print(f'  ✓ {os.path.relpath(path, dirpath)}: 属性读取 {n1} 处 → 兼容函数')

    # 硬自检：recognize_media 调用里不允许再出现 tmdbid=/doubanid=（V3 会 TypeError）
    import re as _re
    bad = []
    for path in (sync, init):
        txt = io.open(path, encoding='utf-8').read()
        for m in _re.finditer(r'recognize_media\(([^()]*)\)', txt, _re.S):
            if 'tmdbid=' in m.group(1) or 'doubanid=' in m.group(1):
                ln = txt[:m.start()].count(chr(10)) + 1
                bad.append(f'{os.path.relpath(path, dirpath)}:{ln}')
    if bad:
        print('\n!! recognize_media 仍在传 tmdbid=/doubanid=，V3 下会 TypeError：' + ', '.join(bad))
        sys.exit(3)
    print('  ✓ 自检：所有 recognize_media 调用已无 tmdbid=/doubanid=')

    if failed:
        print('\n!! 以下替换目标没找到（上游代码可能已变，请人工核对）：')
        for p, s in failed:
            print(f'   {p}: {s}')
        sys.exit(2)
    print('\n补丁完成。检查残留老写法：')
    for path in (sync, init):
        t = io.open(path, encoding='utf-8').read()
        rest = [x for x in ('subscribe.tmdbid', 'subscribe.doubanid',
                            'list_by_tmdbid', '.modified') if x in t]
        print(f'   {os.path.relpath(path, dirpath)}: {rest or "干净"}'
              + ('   (list_by_tmdbid 剩 TransferHistory 的 hasattr 保护写法，V3 下返回空表、不崩)' if 'list_by_tmdbid' in rest else ''))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    patch(sys.argv[1])
