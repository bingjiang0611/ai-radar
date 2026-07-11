# ai-radar

个人精选 AI 内容站。本站只发布用户手动挑选的文章全文翻译、视频/播客总结、B站译制链接；不再保留 RSS / X / 官博客批量采集入口。

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

# B站译制链接
.venv/bin/python src/publish_item.py \
  --url "https://www.youtube.com/watch?v=..." \
  --kind video \
  --title "标题" \
  --bili "https://www.bilibili.com/video/BV..."
```

加 `--deploy` 会在本地渲染验证通过后部署 Cloudflare Pages。

## 本地渲染 / 预览 / 测试

```bash
.venv/bin/python src/run.py
python3 -m http.server -d dist 8787
.venv/bin/python -m unittest discover -s tests
```

`src/run.py` 只渲染当前 SQLite 里的精选内容，不抓取外部源。
