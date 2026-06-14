# ai-radar

个人 AI 资讯聚合站。本地抓多个 AI 信息源 → 去重 → 渲染成静态网站 → 部署到 Cloudflare Pages，无登录分享给几个同事。挑中的条目可补中文全文翻译 / B 站视频链接，长在同一个站。

## 安装

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # 唯一依赖：nh3（HTML 清洗）
```

## 用法

```bash
.venv/bin/python src/run.py                       # 抓 → 去重 → 清洗+图片进站 → retention → 渲染 dist/
.venv/bin/python -m unittest discover -s tests    # 测试
python3 -m http.server -d dist 8787               # 本地预览 → http://localhost:8787
wrangler pages deploy ./dist                      # 部署（需先 wrangler 登录）
```

需要 `python3` + `curl`（macOS 自带）+ `nh3`（唯一 pip 依赖，安全清洗外站正文）。
- 正文：feed 自带全文（清洗后站内展示），图片下载进 `dist/img/`（防丢失），点「打开原文」才外跳。
- retention：只保留近 7 天条目（按发布时间 published_at，无日期退回抓取时间），每次抓取顺带清理过期条目和无引用图片。

## 加信息源

编辑 `config/sources.json`，多数情况加一行（`parser: rss`）即可。详见 `CLAUDE.md`。

## 现状

已实现：RSS/JSON 抓取 → SQLite 去重 → 静态站（来源总览 + 时间流 + 条目详情页）；X/Twitter 列表抓取（twitter-cli，须在 Claude 会话里跑）；标题/摘要中译；JS 站点正文 Jina/直连兜底；视频 YouTube/B站门面。
待做：全文翻译回填（人工挑选条目）、公开部署（wrangler pages）。
