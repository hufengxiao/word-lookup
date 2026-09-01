# Changelog

本项目所有值得记录的变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [v0.7.8] - 2026-09-01

### 修复
- **子义项小标题不污染释义中文**：超长多义动词（run/light/take）的 `<h2 class="shcut">`（如 `manage 管理`）不再把其中文拼进上一条释义的中文行（修复 `管理；经营管理`、`提供，开设…公共汽车；火车` 这类尾部杂字）。

## [v0.7.7] - 2026-09-01

### 修复
- **惯用语/短语词条保留样式**：以 `<span class="idm">` 作词头（如 `fuck me`）或缺少 `<h1 class=headword>` 的词条，不再掉进无样式兜底，详情页有完整深色排版；未知结构的兜底也套用统一样式，避免白屏。

## [v0.7.6] - 2026-09-01

### 修复
- **例句中文支持 `oT` 容器**：牛津例句翻译可能用 `<xT>/<aT>/<oT>` 三种容器，此前漏掉 `oT` 导致部分例句（如 `normal distribution`）没翻译。现统一识别。

## [v0.7.5] - 2026-09-01

### 修复
- **无例句块的词条不再"一大坨"**：没有标准 `<ul class="examples">` 的词条（如 `General American`）不再被整词条正文硬凑成一条超长例句，干净显示、无 EXAMPLE 区。

## [v0.7.4] - 2026-09-01

### 修复
- `<style>` 统一定位到 `<head>` 内，避免部分 Qt 版本把 CSS 声明当正文文本（详情页出现"一堆 div"）。
- 例句英文提取退化分支不再残留 `<span class="gloss">` 这类空开标签（显示为裸标签文本）。

## [v0.7.3] - 2026

### 改进
- 统一中英文字体（`Segoe UI` / 微软雅黑）与色板，词条详情与搜索界面观感一致。

<!-- 以下为早期版本，仅记录关键节点 -->

## [v0.7.0] - 2026

### 新增
- Spotlight 动效抛光：屏幕自适应宽度 + 假毛玻璃浮层 + 透明度渐变 + 唤起浮现动画。

## [v0.5.0] - 2026

### 变化
- 详情改为单窗口内嵌切换（Enter 在列表 ↔ 详情之间），不再额外弹窗。

## [v0.3.x] - 2026

### 新增
- 联想结果带基础释义预览（词头 + 一行中文摘要）。
- 词典库 schema 就地迁移，无需重下。

## [v0.1.0] - 2026-08-19

### 新增
- 首个可用版本：全局热键 + Spotlight 搜索 + MDX 词典构建 + SQLite 索引 + Windows exe 打包。

[unreleased]: 尚未发布
[v0.7.8]: https://github.com/hufengxiao/word-lookup/releases/tag/v0.7.8
[v0.7.7]: https://github.com/hufengxiao/word-lookup/releases/tag/v0.7.7
[v0.7.6]: https://github.com/hufengxiao/word-lookup/releases/tag/v0.7.6
[v0.7.5]: https://github.com/hufengxiao/word-lookup/releases/tag/v0.7.5
[v0.7.4]: https://github.com/hufengxiao/word-lookup/releases/tag/v0.7.4