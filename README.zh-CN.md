# 章鱼简谱（OctoPus）

[English](README.md) | **简体中文**

**章鱼简谱：玩转八度，轻松制谱。**

章鱼简谱（OctoPus）是一款桌面简谱编辑器。使用 JPS（Jianpu Script）编写乐谱时，可实时查看 SVG 预览；
也可以将简谱图片或 PDF 识别为可继续编辑的 JPS 草稿，并将乐谱导出为 SVG、PDF、PNG 或 JPEG。

## 项目背景

本项目采用[番茄简谱](http://zhipu.lezhi99.com)的 JPS 格式，自主实现解析和乐谱排版，并致力于还原
番茄简谱的渲染效果。此外，程序支持在 6/8、9/8 和 12/8 拍号下自动分组音符，也支持识别简谱图片和 PDF。

## 功能

- 使用 JPS 编辑简谱，并实时预览排版效果。
- 识别 JPG、PNG 图片或 PDF 文件中的简谱，生成可继续编辑的 JPS 草稿。
- 将乐谱导出为 SVG、PDF、PNG 或 JPEG；PNG 和 JPEG 图片支持 96 和 300 DPI。
- 可在普通编辑和转录模式之间切换。

## 识谱

图片和 PDF 识谱使用 RapidOCR 和 ONNX Runtime。识别结果是待校对的草稿，使用前请对照原稿检查。较小、模糊或
彼此重叠的符号可能被漏识或误识。如果音符编号匹配率较低，或识别草稿的排版与原稿差异较大，程序会提示复查。
提示可跳转到原稿对应区域；如能匹配到具体音符，也会同时定位该音符。

转录使用内置的**默认**配置，包括 PP-OCRv6 Small 检测和识别模型，以及共用的 PP-OCRv4 Mobile
方向分类器。支持离线中英文识别。模型配置固定；使用草稿前仍应对照原稿检查。

## 后续计划

- 持续提升图片和 PDF 识谱的准确率。
- 增加音频试听、MIDI 导出，以及 LilyPond 和 MusicXML 导出功能。
- 支持导入 MusicXML 并转换为 JPS。
- 支持配置可选的大语言模型 API 密钥，用于图片和 PDF 转录。

## 用户手册

可在程序中选择 **帮助 → 用户手册**，也可阅读[中英文离线手册](docs/user-manual/index.html)。手册介绍编辑流程、
支持的 JPS 记谱方式和当前限制，并随安装包和便携版一同提供。另有[英文 PDF](docs/PDF/OctoPus-User-Manual-en.pdf)
和[中文 PDF](docs/PDF/OctoPus-User-Manual-zh-CN.pdf)。在桌面程序中点击 PDF 链接会弹出保存对话框；在浏览器中
则会直接下载 PDF。

JPS 格式规范见 [Tomato JPS Spec](https://github.com/yetist/jianpu-spec)。本程序的 JPS 输入格式遵循该规范。

## 字体

Windows 和 macOS 桌面版本优先使用系统已安装的对应字体；首选字族缺失时使用兼容的已安装替代字体。
可通过**帮助 → 字体**查看官方安装说明或重新检查。这两个平台的桌面包不包含程序的 13 种乐谱字体。
Linux 便携版和 AppImage 直接使用随程序提供并经过验证的乐谱字体集。离线手册仅附少量独立的
Noto Sans SC 子集，不属于乐谱字体集。请参阅[字体资源说明](src/octopus/assets/fonts/README.zh-CN.md)
了解平台映射、字体许可与打包方式。

## 源码构建

运行环境和构建要求请参阅[环境说明](ENVIRONMENT.zh-CN.md)。生产构建使用锁定的 Python、Node/npm、Rust
版本和 Tauri CLI 2.11.5。在项目根目录运行环境配置脚本：

```sh
python3 scripts/setup.py
```

Linux 构建还需要 GTK/WebKit 开发包和 Poppler 工具，详见 [Linux 系统依赖](ENVIRONMENT.zh-CN.md#linux-系统依赖包)。
请在目标系统上构建；Python 引擎无法交叉编译。

构建 Linux 便携版：

```sh
python3 scripts/build_portable.py
```

Windows 便携版构建：

```powershell
py scripts\build_portable.py
```

如明确需要安装包，Linux 可加 `--bundles appimage`，Windows 可加 `--bundles nsis`。启动器会从脚本位置定位仓库并检查构建依赖，因此可在任意工作目录调用。

Windows 构建默认还会生成便携 ZIP。发布文件统一使用
`OctoPus_{version}_{arch}_{os}_{purpose}.{ext}`：Windows 便携 ZIP 以
`_x64_win64_portable.zip` 结尾，Windows 安装程序以 `_x64_win64_setup.exe` 结尾，Linux
AppImage 以 `_x64_linux.AppImage` 结尾且不带 purpose。架构可为 `x64` 或 `arm64`。检查通过的
便携版目录仍位于 `dist/<target-triple>/portable/`；临时构建文件位于 `build/`。

## 运行便携版

Linux x86_64 下，运行：

```sh
./dist/x86_64-unknown-linux-gnu/portable/usr/bin/octopus
```

Windows 下，运行 `dist/<target>/portable/` 中的 `octopus.exe`。请保留完整的便携版目录，其中包含程序资源、
Python 引擎和示例乐谱。Linux 依赖系统中的 GTK/WebKit 运行库和 Poppler 工具；Windows 需要 WebView2。

## 免责声明

章鱼简谱基于 GNU 通用公共许可证第 3 版发布。本软件免费提供，作者不提供任何形式的担保，也不对因使用本软件
造成的直接或间接损失承担责任。

章鱼简谱通过 AI 辅助开发，并将以此方式维护。
