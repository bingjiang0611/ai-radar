# CLAUDE.md — ai-radar

个人精选 AI 内容站。产品方向已经从“自动资讯聚合”收敛为“用户手动挑选内容后上传”：文章全文翻译、视频/播客总结、单条公开 X 视频、B站译制链接 → SQLite → 静态站 → 用户明确要求时部署到 Cloudflare Pages。

## 当前运营策略

- 不跑 RSS/X/官博客批量采集，不做每日自动部署。
- 唯一日常写入口是 `src/publish_item.py`。
- `.venv/bin/python src/run.py` 只渲染精选内容，不访问外部源。
- 只有用户明确说“部署 / 上线 / 发布”时才部署 Cloudflare Pages。
- 从 Etch 等内容工具发布时只读取当前已完成成果；不触发、不等待新的总结、翻译、重生成或配图流程。当前内容不足 `publish_item.py` 的载荷要求时停止并说明缺失项。
- 不清空或重建 `data/radar.db`，除非用户明确要求。

## 架构

- 真源：`data/radar.db`。
- 去重：`store.url_hash(normalize_url(url))`，剥 `utm_*`、常见追踪参数，排序剩余 query。
- 精选判定：`source_id == "user-curated"`，或存在 `translation_md` / `summary_md` / B站 `video_url`。
- 渲染：`src/render.py` 只生成 `dist/index.html` 和 `dist/item/<hash>.html`；旧 `feed.html` / `reads.html` / `sources.html` 会在渲染时删除。
- 视频：YouTube/B站用 lite facade；单条公开 X status 视频用 X 官方 `twitter-tweet` embed + `platform.twitter.com/widgets.js`，这不是批量抓 X。
- X 视频封面是硬门禁：必须从 `tweet-result` 的 `video.poster` / `mediaDetails[].media_url_https` 取真实媒体封面，落到 `dist/img/` 后通过 `publish_item.py --cover /img/...` 写入；没有真实封面不发布、不部署。
- 内容清洗：`content.process()` 用 `nh3` 清洗 HTML，并把正文图片下载到 `dist/img`；视频封面直接使用 YouTube `hq720` URL，X 卡片封面优先使用 `tweet_meta.cover`。
- retention：`purge_old(7)` 只清理历史普通采集残留；人工精选内容永久保留。

## 怎么跑

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python src/run.py
.venv/bin/python src/publish_item.py --url URL --kind article --title "标题" --translation /tmp/zh.md
.venv/bin/python -m unittest discover -s tests
```

部署：

```bash
npx --yes wrangler pages deploy ./dist --project-name ai-radar --branch main
```

## 改完代码后的验证 profile

### L1 静态 oracle

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python src/run.py
git diff --check
```

### L2 运行时 smoke

```bash
python3 -m http.server -d dist 8787
```

打开 `http://localhost:8787` 检查：首页非空、卡片可进入详情页、文章中文翻译 tab / 视频总结 tab 可读、无 Traceback 或明显错误文本。

### L3 用户路径

- 发布路径：用 `src/publish_item.py` 建/更新条目后检查首页与详情页。
- 渲染路径：跑 `src/run.py` 后本地预览首页、详情页、封面、中文内容 tab。
- X 视频路径：首页卡片必须是 `has-img`，不能是 `poster` fallback；封面资源必须 `HTTP 200 image/*`。
- 部署路径：只有用户明确要求部署时才跑 wrangler；部署后验证 `https://ai-radar-do7.pages.dev` HTTP 200 和页面内容。

### 最终回复必须说明

写清实际完成的验证层级、命令结果、是否渲染 `dist`、是否启动/检查本地预览、是否部署，以及未覆盖路径。

## Git 提交身份与推送

- 本仓库所有提交固定使用 GitHub 账号 `bingjiang0611 <307659028+bingjiang0611@users.noreply.github.com>`，不配置、不使用公司邮箱或其他身份。
- 任务完成并通过验证后，默认 `commit` 并 `push` 到 `origin/main`；用户明确要求不提交、不推送或仅提供方案时除外。

## 边界

- 不恢复 RSS/X/browser 批量采集。
- 不新增访问计数 / 收藏 / 赞踩。
- 不绕过 `publish_item.py` 临时拼 SQLite，除非是在修补脚本本身。
