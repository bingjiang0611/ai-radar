# ai-radar

个人精选 AI 内容站。本站只发布用户手动挑选的文章全文翻译、视频/播客总结、B站译制链接；支持手动发布单条公开 X 视频并原生嵌入，不保留 RSS / X / 官博客批量采集入口。

## 安装

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 发布一条精选内容

```bash
# 文章译文
.venv/bin/python src/publish_item.py \
  --url "https://example.com/original" \
  --kind article \
  --title "标题" \
  --translation /tmp/zh.md

# 视频/播客总结
.venv/bin/python src/publish_item.py \
  --url "https://www.youtube.com/watch?v=..." \
  --kind video \
  --title "标题" \
  --summary /tmp/sum.md

# 单条公开 X 视频总结
.venv/bin/python src/publish_item.py \
  --url "https://x.com/user/status/..." \
  --kind video \
  --title "标题" \
  --summary /tmp/sum.md \
  --cover "/img/x-video-cover.jpg"

# B站译制链接
.venv/bin/python src/publish_item.py \
  --url "https://www.youtube.com/watch?v=..." \
  --kind video \
  --title "标题" \
  --bili "https://www.bilibili.com/video/BV..."
```

加 `--deploy` 会在本地渲染验证通过后部署 Cloudflare Pages。

X 视频封面优先从 `https://cdn.syndication.twimg.com/tweet-result?id=<status_id>&token=<random>` 的 `video.poster`
或 `mediaDetails[].media_url_https` 取真实媒体图，落到 `dist/img/` 后通过 `--cover /img/...` 写入。
不要用无关配图或生成图替代视频封面。

## 本地渲染 / 预览 / 测试

```bash
.venv/bin/python src/run.py
python3 -m http.server -d dist 8787
.venv/bin/python -m unittest discover -s tests
```

`src/run.py` 只渲染当前 SQLite 里的精选内容，不抓取外部源。

## MiniMind 互动教程

线上入口：<https://ai-radar-do7.pages.dev/minimind/>，也可从首页导航的「互动教程」进入。

`static/minimind/` 保存独立 `minimind-lab` 项目的生产构建快照；所有渲染入口都会把它挂载到 `dist/minimind/`，不会覆盖首页、文章或图片。普通内容发布不需要安装 Node.js 或依赖相邻源码目录。

教程更新、验证与部署步骤见 [docs/minimind.md](docs/minimind.md)。
