# MoviePilot Plugins（自定义插件仓库）

MoviePilot 自定义插件仓库，发布家庭 NAS 上自己维护的插件（同时支持 MP v2 与 v3）。

- GitHub：`https://github.com/metack567-stack/moviepilot-plugins`（public）
- 仓库结构：
  - `package.v2.json` + `plugins.v2/<插件名>/` —— MP v2 插件清单与源码
  - `package.v3.json` + `plugins.v3/<插件名>/` —— MP v3 插件清单与源码（条目含 `system_version`；插件目录内含 `pyproject.toml` 依赖清单）
- 同步位置：NAS `/vol1/1000/Docker/dev-workspace/projects/moviepilot-plugins/`

---

## 插件清单

### P115StrgmSubBt0「115网盘追更·Bt0磁力版」（v1.7.x）

结合 MoviePilot 订阅功能，自动搜索 115 网盘资源并转存缺失的电影和剧集（内置 bt0 磁力搜索源）。

| 项 | 值 |
|---|---|
| 插件名 | 115网盘追更·Bt0磁力版 |
| 版本 | 1.7.x（`plugin_version` 与 `package.v2.json` / `package.v3.json` 的 `version` 三处同步维护） |
| 容器路径 | `/app/app/plugins/p115strgmsubbt0/` |
| 日志 | 容器内 `/config/logs/plugins/p115strgmsubbt0.log` |
| cron | `30 2,10,18 * * *`（2:30 / 10:30 / 18:30） |
| 搜索源 | pansou（115 网盘）> bt0（磁力，经 2bt0-hub） |
| 依赖 | 115网盘STRM助手（p115strmhelper）插件的离线下载服务 |

**功能要点**：
- 电影/剧集订阅自动搜索 115 资源并转存/离线下载
- 剧集磁力择优：按「覆盖缺失集数, 磁力总集数」最大提交
- 离线回查（>30min，复用缓存）+ **以媒体库入库为完成标准**（未入库保持等待）
- 历史去重：bt0 提交后 7 天内跳过重复搜索
- 影片落盘：115「最近接收/MP」，由 115 助手网盘整理自动入库

**关键代码**（`plugins.v2/p115strgmsubbt0/handlers/`，v3 目录为同一份代码）：
- `sync.py`：订阅同步主流程（离线回查/入库判定/完成订阅）
- `search.py`：搜索源（pansou/bt0/hdhive）、剧集解析
- `subscribe.py`：`check_and_finish_subscribe`（完成订阅封装）
- `clients/bt0.py`：bt0 客户端与剧集集数解析

---

## 1.7.18 修复（2026-11-13，仅 plugins.v3）

电影订阅被「同名剧集」污染的根因与修法（起因：订阅电影《欢迎来龙餐馆》，结果入库了 12 集日番《直至魔女消逝》）。

- **bt0 精确匹配不做类型校验**：`clients/bt0.py::resolve()` 只校验「标题 + 年份」，命中后把该 `movie_id` 下的**全部磁力**都当电影资源返回，完全没有分集/季集判断。而 2bt0-hub 的 `category` 字段不可靠——实测该电影条目名下的磁力是 `欢迎来龙餐馆[共12部合集]...Once.Upon.a.Witchs.Death.S01.2025...`，`category` 却仍返回「电影」，所以靠 category 过滤无效。
- **整包磁力绕过文件级校验**：1.7.17 只在「从磁力结果里挑单个文件」阶段拒绝 `SxxEyy`，但这条是整季合集磁力直接提交 115 离线 → 整包入库，压根没走到挑文件那一步。
- **修法**：新增 `utils/file_matcher.py::looks_like_series()`，按强特征识别剧集资源（`S01E05`、裸季号 `S01`、`第N集`、`全N集`、`EP01`、`Season 1`；不把电影套装「共4部合集」算进去），在三个位置使用：
  1. `handlers/search.py::_search_bt0()` 精确匹配路径（逐条磁力剔除，全被剔除则降级模糊搜索）
  2. `handlers/search.py::_search_bt0()` 模糊搜索路径（与原有 category 判断并用）
  3. `handlers/sync.py::process_movie_subscribe()` 提交前兜底（覆盖 PanSou 等分享链接源）
- 剔除时均打 WARNING 说明原因与条数，便于回溯；剧集订阅完全不受影响。
- 已入库的错片需人工处理：《直至魔女消逝 (2025)》是电影订阅带进来的错误剧集，115 影视库与 Emby 中的条目需自行清理。

---

## 1.7.17 修复（2026-11-12，仅 plugins.v3）

容器 moviepilot-v3 曾长期停留在 1.7.11，排查后一次性升级到 1.7.17（docker cp plugins.v3/p115strgmsubbt0/. moviepilot-v3:/app/app/plugins/p115strgmsubbt0/ + docker restart moviepilot-v3）。

- **bt0 全量 401**：2bt0-hub 全站 API 强制 X-API-Key。clients/bt0.py 现在在配置 bt0_apikey 为空时自动从 hub /api/apikey 获取，收到 401 会清缓存重取；hub 密钥持久化在 /data，容器重建不变。
- **剧集订阅长期空转**：handlers/sync.py 取 no_exists 用 mediainfo.tmdb_id，而 V3 返回的 key 是 tmdb:2288 格式，永远取不到，只打印「没有缺失剧集信息」。现在 mediakey 不匹配时按季号遍历兼容读取，仍为空再用订阅 total_episode/lack_episode 兜底。
- **电影误收剧集单集**：分享文件名含 SxxEyy / 第N集 / [全N集] 时跳过，不再把剧版单集当电影转存并误判订阅完成。
- **接管态补锁死循环**：旧判断 str(sites) != "[-1]"，而写入端按 storage 写成 "123"；更深层原因是 MP V3 的 SubscribeOper.update 会忽略 sites 字段、写入不落库，导致每 5 分钟重复补锁刷屏。现在改为按实际 115 站点 ID 判断 + 写入后回读校验，确认不落库则打一次 WARNING 并停止后续补锁（订阅站点保持原状，不改变行为）。如需让「仅115」接管真正生效，需改用原生 SQL 写 subscribe.sites，同时处理开放时段的站点恢复，避免锁死。
- **执行记录看不见空跑**：transferred_count == 0 时追加一条「本次同步无新增」记录（最多保留 50 条）。
- **package.v3.json 不是合法 JSON**：history 多个条目缺逗号，V3 插件市场读不到新版清单，也是容器长期停留旧版的原因之一，已修正并补齐 1.7.17 条目。
- 另：系统通知渠道 telegram（TELEGRAM_CHAT_ID 指向 bot 自身）长期 403，已在 systemconfig.Notifications 中禁用，原值备份在 config/plugins_backup/Notifications-backup-*.json；企业微信/飞书等渠道不受影响。

> 版本线说明：plugins.v2 仍停留在 1.7.11，本次只维护 V3 分支；改版本号只需同步 plugins.v3/.../__init__.py 的 plugin_version 与 package.v3.json 的 version 两处。

## V3 支持（2026-10-11 新增）

NAS 上的 MoviePilot 已升级到 V3（容器名 `moviepilot-v3`，镜像 `jxxghp/moviepilot-v3`）。本仓库为此增加 V3 布局，两套清单并存、互不影响。

**V3 关键差异**：
1. **清单文件不同**：V3 只读 `package.v3.json`（条目需带 `"system_version": ">=3.0.0"`），源码放 `plugins.v3/<插件名>/`；没有 v3 清单的仓库，V3 插件市场看不到、也不会建立"仓库绑定"。
2. **依赖清单是 V3 装依赖的唯一入口**：插件目录里必须有 `pyproject.toml`（优先）或 `requirements.txt`，V3 启动时才会用 `uv pip install` 装依赖；没有这个文件 → 插件永远停在"等待依赖"、无法加载。
3. **必须显式钉 `python-concurrenttools==0.1.8`**：`p115client==0.0.9.6.5.1` 依赖它的 `threadpool_map`，而 uv 默认会解析 PyPI 上更新的 0.1.9（该 API 已改名）⇒ 不钉就 `ImportError: cannot import name 'threadpool_map'`，插件起不来。
4. 依赖 wheel 随插件目录携带（`wheels/`），V3 用 `uv pip install --find-links <插件目录>/wheels` 离线安装；`p115client` 在 PyPI 上取不到该版本，因此 **`wheels/` 目录必须随插件一起分发**。
5. 依赖装好或代码更新后，**必须重启容器**（`docker restart moviepilot-v3`）V3 才会重新分类并加载插件。

---

## 安装方式

1. **插件市场（推荐）**：MoviePilot → 插件市场 → 添加自定义仓库 `https://github.com/metack567-stack/moviepilot-plugins` → 安装 P115StrgmSubBt0
   （V3 走 `package.v3.json` + `plugins.v3/`；V2 走 `package.v2.json` + `plugins.v2/`）
2. **手动部署（开发用）**：`docker cp plugins.v3/p115strgmsubbt0 moviepilot-v3:/app/app/plugins/` + `docker restart moviepilot-v3`

> 注意：MP 按**版本号**检测更新；改代码必须同步升 `plugin_version` 和 `package.v2.json`/`package.v3.json` 的 `version`（共三处），否则 MP 看不到新版本。

---

## 开发与部署流程（标准）

```
1. 在 NAS 工作区改代码：
   /vol1/1000/Docker/dev-workspace/projects/moviepilot-plugins/plugins.v2/p115strgmsubbt0/
   （v3 目录为同一份代码的副本，改完一并同步）
2. 同步到容器：
   docker cp .../handlers/<文件> moviepilot-v3:/app/app/plugins/p115strgmsubbt0/handlers/
3. 校验：docker exec moviepilot-v3 python3 -m py_compile ...（全文件）
4. 重启：docker restart moviepilot-v3（插件重载生效）
5. 验证：回读容器内文件 + 看插件日志无 ERROR
6. 升版本：改 plugin_version + package.v2.json version + package.v3.json version（三处）
7. 提交：git add + commit + push（NAS 上 git 操作）
```

**约束**：
- 不直接改容器内文件（容器重建会丢）；代码只改 NAS 工作区
- 改动涉及行为/路径/版本 → 同步更新本 README 和 `dev-workspace/docs/` 文档
- 2bt0-hub（`/vol1/1000/Docker/2bt0-hub`）是只读资源源，不要改
- 依赖清单（`pyproject.toml`）里的版本钉死不要随手升级：`p115client==0.0.9.6.5.1` 必须配 `python-concurrenttools==0.1.8`

---

## 文档索引

- `docs/影视系统链路总览.md`：影视链路、订阅链路、媒体库、排查（dev-workspace/docs）
- `docs/NAS操作指南.md`：目录地图、文件放置规则、备份与恢复（dev-workspace/docs）

---

*维护规则：任何行为/路径/版本变更后，同步更新本 README 与外部文档。*
