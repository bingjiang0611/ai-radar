# ai-radar

个人 AI 资讯聚合站。本地抓多个 AI 信息源 → 去重 → 渲染成静态网站 → 部署到 Cloudflare Pages，无登录分享给几个同事。挑中的条目可补中文全文翻译 / B 站视频链接，长在同一个站。

## 用法

```bash
python3 src/run.py                     # 抓全部启用源 → 去重写库 → 渲染 dist/
python3 -m unittest discover -s tests  # 测试
# 本地预览
python3 -m http.server -d dist 8787    # → http://localhost:8787
# 部署（需先 wrangler 登录）
wrangler pages deploy ./dist
```

纯 Python 标准库，无 pip 依赖、无构建链。需要 `python3` 和 `curl`（macOS 自带）。

## 加信息源

编辑 `config/sources.json`，多数情况加一行（`parser: rss`）即可。详见 `CLAUDE.md`。

## 现状

第一刀：RSS/JSON 抓取 → SQLite 去重 → 静态 feed 站。
待做：Twitter 列表抓取（browser-use，须在 Claude 会话里跑）、标题/摘要中译、条目详情页 + 全文翻译回填、公开部署。
