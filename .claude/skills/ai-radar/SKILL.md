---
name: ai-radar
description: >
  运营 ai-radar 个人精选 AI 内容站。用户给文章译文、YouTube/播客/视频总结、单条公开 X 视频、
  B站译制链接、Etch 当前已有成果或对应 markdown 文件时，Codex 把这条精选内容发布到站点并按需部署。
  不要抓 RSS、X/Twitter、官博客或任何批量来源。Use when the user says 上传到 radar / 发布 radar / 部署 radar /
  翻译这篇上传 / 上传总结 / 挂 B站链接 / 运营 ai-radar。
---

# ai-radar 发布 runbook

ai-radar 是人工精选内容发布器：

**用户给内容 → `publish_item.py` 入库/挂载 → 渲染验证 → 用户明确要求时部署 Cloudflare Pages。**

## 硬边界

- 不跑每日自动化，不恢复批量采集。
- 不运行 RSS/X/browser/官博客批量抓取；相关 legacy 代码已经删除。用户手动点名的一条公开 X 视频可作为普通 `--url` 发布。
- `.venv/bin/python src/run.py` 只 render 当前精选库，不访问外部源。
- 精选内容有 `translation_md` / `summary_md` / B站 `video_url` 时不会被 7 天 retention 删除。
- 部署是真实公开发布；只有用户这次明确要“部署/上线/发布”时才加 `--deploy` 或手动跑 wrangler。
- Etch 等内容工具一律视为只读来源：只使用任务当前已经完成、可读取的成果；禁止点击“追加总结 / 生成 / 重新生成 / 翻译 / 配图”等按钮，禁止为了发布启动或等待新的内容处理。

## 输入要求

收到用户内容时，先从消息或文件里提取这些字段；缺关键字段才问：

- `url`：原文、YouTube、公开 X status、播客或视频 URL。没有 URL 必须补问。
- `kind`：`article` / `video` / `podcast`。
- `title`：新条目需要标题；markdown 第一行 `# 标题` 可代替。
- 内容载荷至少一个：
  - `--translation <file.md>`：文章全文中文翻译。
  - `--summary <file.md>`：视频/播客/文章中文总结。
  - `--bili <url>`：B站译制视频链接。

### Etch 当前成果

用户说“部署 Etch 中这个内容”时：

- 读取当前已有的标题、来源 URL、已完成 markdown、B站链接或封面；状态为 `running` / `pending` / `checkpoint` 的阶段不推进、不等待。
- 允许做发布必需的机械整理，例如移除尚未生成的图片占位、规范 markdown 和复制已经存在的本地图；不得扩写、重写或另行生成正文、翻译、总结与配图。
- 当前成果已满足 `publish_item.py` 的载荷要求就直接发布；不满足时明确列出缺失项并停止，请用户先在来源工具中完成，不能擅自补跑流程。

如果用户给的是 Obsidian 文件路径，先读文件。YAML frontmatter 会由脚本剥掉；但发布前必须处理这些 Obsidian/本地格式：

- `![[attachments/...]]` 图片不会自动渲染，先复制到 `dist/img/` 并转成标准 `![说明](/img/...)`，否则脚本会拒绝。
- `file:///...` 本地图也不会被浏览器线上访问，必须复制到 `dist/img/` 并转成 `/img/...`。
- 发布含表格的长文后，机械检查详情页里不能残留原始 pipe table 文本（例如 `<p>| 路线 | ...`）；应渲染为 `<table>`。

## 唯一日常命令

```bash
cd ~/IdeaProjects/vibecoding/ai-radar

.venv/bin/python src/publish_item.py \
  --url "https://example.com/original" \
  --kind article \
  --title "标题" \
  --translation /tmp/zh.md
```

视频/播客总结用 `--summary /tmp/sum.md`；B站译制链接用 `--bili "https://www.bilibili.com/video/BV..."`。

用户明确说部署时加 `--deploy`。用户没明确说部署时只本地渲染验证。

可选参数：

- `--title-zh "中文标题"`：页面优先显示中文标题。
- `--summary-text "卡片摘要"`：给首页卡片摘要。
- `--summary-zh`：把 `--summary-text` 写入中文摘要字段。
- `--content /tmp/original.md`：可选，把原文/简介 markdown 放进原文 tab。
- `--cover "/img/cover.jpg"`：可选，显式首页卡片封面；X 视频必须优先使用真实 poster。
- `--no-render`：只写库，不渲染。日常少用。

单条 X 视频封面经验：

- 先查 `https://cdn.syndication.twimg.com/tweet-result?id=<status_id>&token=<random>`。
- 优先取 `video.poster`，其次取 `mediaDetails[].media_url_https`；这是原推文真实媒体封面。
- 如果本机直连 `pbs.twimg.com` / `video.twimg.com` 超时，可用图片代理下载一次后落到 `dist/img/`，再用 `--cover /img/...`。
- 不要用搜索到的泛 Motion 图、AI 生成图或无关配图替代；拿不到真实封面就明确标阻塞。
- 这是硬门禁，不是审美建议：X 视频没有真实封面时不要发布，不要部署。

## 部署验证

`publish_item.py` 默认会渲染并做机械验证：

- `dist/index.html` 存在且非空。
- 首页没有明显 `Traceback` / `SyntaxError` / `error:`。
- 首页能找到本次 item。
- `dist/item/<hash>.html` 已生成。
- 若本次是 X 视频：首页该卡片必须包含 `has-img` 和封面路径，不能是 `poster` fallback；封面 URL 必须能返回 `HTTP 200 image/*`。

带 `--deploy` 时，脚本在验证通过后运行：

```bash
npx --yes wrangler pages deploy ./dist --project-name ai-radar --branch main
```

部署后再轻验线上：

```bash
curl -fsSI https://ai-radar-do7.pages.dev
curl -fsL https://ai-radar-do7.pages.dev | head
```

回报用户时说明：发布的标题、类型、是否新建条目、部署 URL、线上 HTTP 是否 200。缺 wrangler 登录时停下，让用户自己 `npx wrangler login`。
