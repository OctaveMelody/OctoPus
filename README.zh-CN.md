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

## 后续计划

- 持续提升图片和 PDF 识谱的准确率。
- 增加音频试听、MIDI 导出，以及 LilyPond 和 MusicXML 导出功能。
- 支持导入 MusicXML 并转换为 JPS。

## 用户手册

可在程序中选择 **帮助 → 用户手册**，也可阅读[中英文离线手册](docs/user-manual/index.html)。手册介绍编辑流程、
支持的 JPS 记谱方式和当前限制，并随安装包和便携版一同提供。另有[英文 PDF](docs/PDF/OctoPus-User-Manual-en.pdf)
和[中文 PDF](docs/PDF/OctoPus-User-Manual-zh-CN.pdf)。在桌面程序中点击 PDF 链接会弹出保存对话框；在浏览器中
则会直接下载 PDF。

JPS 格式规范见 [Tomato JPS Spec](https://github.com/yetist/jianpu-spec)。本程序的 JPS 输入格式遵循该规范。

## 源码构建

运行环境和构建要求请参阅[环境说明](ENVIRONMENT.zh-CN.md)。从源码构建需要 Python 3.11+、uv、Node.js 20.19+
（含 npm）、Rust 1.92+ 和 Tauri CLI 2.11.5。在项目根目录运行环境配置脚本：

```sh
python3 scripts/setup.py
```

Linux 构建还需要 GTK/WebKit 开发包和 Poppler 工具，详见 [Linux 系统依赖](ENVIRONMENT.zh-CN.md#linux-系统依赖包)。
请在目标系统上构建；Python 引擎无法交叉编译。

构建 Linux 安装包和便携版：

```sh
python3 build.py --bundles deb
```

请在 Windows 本机环境下构建：

```powershell
python build.py --bundles nsis
# 或：python build.py --bundles msi
```

安装包和便携版会生成在 `dist/` 下对应平台的子目录中；临时构建文件位于 `build/`。

## 运行便携版

Linux x86_64 下，运行：

```sh
./dist/x86_64-unknown-linux-gnu/portable/usr/bin/octopus
```

Windows 下，运行 `dist/<target>/portable/` 中的 `octopus.exe`。请保留完整的便携版目录，其中包含程序资源、
Python 引擎和示例乐谱。Linux 依赖系统中的 GTK/WebKit 运行库和 Poppler 工具；Windows 需要 WebView2。

## 字体

字体可按用途分别设置。程序会优先使用**偏好设置**中指定的系统字体；若该字体不可用，则改用随应用附带、
获得相应使用许可的字体。导出 PDF 时，字体会嵌入文件；使用外部 SVG 查看器时，需确保查看器能访问
乐谱所用字体。字体映射、回退机制和许可信息详见[字体指南](src/octopus/assets/fonts/README.zh-CN.md)。

## 免责声明

章鱼简谱基于 GNU 通用公共许可证第 3 版发布。本软件免费提供，作者不提供任何形式的担保，也不对因使用本软件
造成的直接或间接损失承担责任。

章鱼简谱通过 AI 辅助开发，并将以此方式维护。
