# MiniMind 互动教程部署

- 公共入口：<https://ai-radar-do7.pages.dev/minimind/>。
- 首页入口：沿用原站导航样式的「互动教程」链接，不改文章内容或数据库类型。
- 教程源码：独立 `minimind-lab` 仓库，构建版本 `4746530`。
- 课程参考源码：MiniMind `6fc918beb68a0d8c40452338df6319fe168014ba`。
- 快照：`static/minimind/`，包含 HTML、带内容哈希的 JS/CSS、字体、favicon 和第三方许可证；无用户进度、环境变量、模型或数据库。
- 发布目标：Cloudflare Pages 项目 `ai-radar`、生产分支 `main`。部署不等于 git push。

## 为什么不只复制到 dist

`dist/` 是运行产物，不是可重建的真源。把快照纳入本仓库后，`render_site()` 每次将其复制到 `dist/minimind/`，所以 `run.py` 和 `publish_item.py` 发布文章时都会保留教程。缺失快照会在修改原页面前报错，不静默发布坏链接。

教程使用 `/minimind/` 构建 base，JS/CSS/font/favicon 都在该前缀下，不依赖 URL 是否保留末尾斜杠。带内容哈希的 `/minimind/assets/*` 使用一年 immutable 缓存，HTML 留 Cloudflare Pages 默认策略。

教程与主站 CSS/JS 完全隔离。学习进度用 `minimind-lab-progress-v1` 本地存储键，不覆盖主站的 `air-*` 设置。不同域名的学习进度不会自动迁移。

## 更新教程

以下假设两个仓库位于同一父目录：

```sh
cd ../minimind-lab
npm ci
npm test
npm run build -- --base=/minimind/

cd ../ai-radar
mkdir -p static/minimind
cp -R ../minimind-lab/dist/. static/minimind/
.venv/bin/python -m unittest discover -s tests
.venv/bin/python src/run.py
.venv/bin/python -m http.server 8787 --bind 127.0.0.1 --directory dist
```

检查本地首页 → 互动教程 → 实验按钮；检查文章详情仍正常。更新本文件里的教程构建版本；只同步构建文件，不复制 node_modules、源码私有配置或本地数据。升级后可删除 `static/minimind/assets/` 中已不被构建引用的旧哈希文件，但不要清理无关目录或 Pi 运行时状态。

用户明确要求部署后：

```sh
npx --yes wrangler pages deploy ./dist --project-name ai-radar --branch main
```

上线验证首页、`/minimind/` 与 `/minimind` 的 HTTP 响应、HTML 引用资源的 HTTP 状态与类型，并在浏览器点击一次实验。生产分享使用稳定站点域名，不使用每次变化的部署预览域名。

## 本次验证范围

- L1：MiniMind 子路径生产构建通过；AI Radar 34 项 Python 测试通过，包括资源前缀、重复渲染挂载与缺包保护；`dist` 已重新渲染。
- 内容保护：部署前保留数据库与 dist 备份；渲染前后 27 条数据库记录、27 个详情页不变；原生产首页 10 个详情链接全部保留。
- L2：启动本地 8787 HTTP 预览，在浏览器从首页「互动教程」进入实际构建页面。
- L3：2026-09-07 已部署，部署版本 `7484e93`，预览地址 <https://badf2fda.ai-radar-do7.pages.dev>。稳定域名首页、`/minimind/`、不带斜杠的 `/minimind` 均验证 HTTP 200；12 个教程文件逐字节与本地构建一致，JS/CSS/font/favicon 类型正确，哈希资源 immutable 缓存生效。
- 线上浏览器已点击「生成下一个 token」，确认上下文从「今天的天空」更新为「今天的天空很」，候选概率同步改变。原生产首页详情链接保留。
- 未对原站所有视频播放、所有译文 tab 或教程全部九关重新做人工逐项验收。教程完整通关测试已在其源码仓库完成。
