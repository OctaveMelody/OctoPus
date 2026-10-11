# 章鱼简谱（OctoPus）— 简谱编辑器

[English](README.md) | **简体中文**

**OctoPus：Oct（八度）+ Pus（简谱）= 终极简谱编辑器。**

章鱼简谱（OctoPus）是一款桌面简谱编辑器。乐谱使用 JPS（Jianpu Script）编写，并实时渲染为 SVG
预览。程序还可以将简谱图片和 PDF 文件识别为可编辑的 JPS 草稿，并将乐谱导出为 SVG、PDF、PNG 或 JPEG。

## 项目背景

章鱼简谱采用[番茄简谱](http://zhipu.lezhi99.com)的 JPS 格式，并通过独立的解析器和乐谱渲染器，
力求匹配番茄简谱的渲染效果。程序还增加了 6/8、9/8 和 12/8 拍号下的音符自动分组，以及图片和 PDF 识谱功能。

## 功能

- 编辑 JPS 乐谱，并实时预览排版结果。
- 将 JPG 或 PNG 乐谱图片及 PDF 文件识别为可编辑的 JPS 草稿。
- 将乐谱导出为 SVG、PDF、PNG 或 JPEG。位图导出支持 96 和 300 DPI。
- 提供普通和识谱两种布局。

## 识谱

图片和 PDF 识谱使用 RapidOCR 与 ONNX Runtime。识别结果为待校对草稿，使用前应与原稿核对。
较小、模糊或相互重叠的记号可能遗漏或误识别。当音符编号匹配度较低，或渲染草稿与原稿差异较大时，
程序会生成复查提示。提示可定位到相关原稿区域；在能够对应的情况下，也会定位到相应音符。

## 后续计划

- 长期持续提高图片和 PDF 识谱的准确率。
- 增加音频播放、MIDI 导出，以及 LilyPond 和 MusicXML 导出。
- 支持导入 MusicXML 并转换为 JPS。

## 用户手册

在程序中选择 **帮助 → 用户手册**，或阅读[中英文离线手册](docs/user-manual/index.html)。手册介绍编辑流程、
支持的 JPS 记谱和当前限制，并随安装包和便携版附带。另有[英文 PDF](docs/PDF/OctoPus-User-Manual-en.pdf)
和[中文 PDF](docs/PDF/OctoPus-User-Manual-zh-CN.pdf)。在桌面程序中点击手册的 PDF 链接会打开保存对话框；
在浏览器中则会下载 PDF。

JPS 源格式规范见 [Tomato JPS Spec](https://github.com/yetist/jianpu-spec)，章鱼简谱使用该规范处理 JPS 输入。

## 源码构建

运行环境和构建要求见[环境说明](ENVIRONMENT.zh-CN.md)。源码构建需要 Python 3.11+、uv、Node.js 20.19+
（含 npm）、Rust 1.92+ 和 Tauri CLI 2.11.5。在仓库根目录运行环境准备脚本：

```sh
python3 scripts/setup.py
```

Linux 构建还需要 GTK/WebKit 开发包和 Poppler 工具，详见 [Linux 系统依赖](ENVIRONMENT.zh-CN.md#linux-系统依赖包)。
请在目标操作系统上构建；Python 引擎不支持交叉编译。

构建 Linux 安装包和便携版：

```sh
python3 build.py --bundles deb
```

Windows 请在原生 Windows 构建环境中运行：

```powershell
python build.py --bundles nsis
# 或：python build.py --bundles msi
```

安装包和便携版生成在 `dist/` 下按目标平台区分的子目录中。临时构建文件保存在 `build/`。

## 运行便携版

Linux x86_64：

```sh
./dist/x86_64-unknown-linux-gnu/portable/usr/bin/octopus
```

Windows：运行 `dist/<target>/portable/` 中的 `octopus.exe`。请保留完整的便携版目录，其中包含程序资源、
Python 引擎和乐谱示例。Linux 需要主机上的 GTK/WebKit 运行库和 Poppler 工具；Windows 需要 WebView2。

## 字体

对于每种字体角色，程序会优先使用已配置的系统字体；如果不可用，则回退到随附的许可合规字体。
可在**偏好设置**中配置字体。PDF 导出会嵌入字体；外部 SVG 查看器需要能够访问乐谱引用的字体。
字体对应关系、替换规则和许可证详情见[字体指南](src/octopus/assets/fonts/README.zh-CN.md)。

## 免责声明

章鱼简谱基于 GNU 通用公共许可证第 3 版发布。本软件免费提供，作者不作任何形式的担保，亦不承担因使用本软件
所导致的任何直接或间接损失。

本软件使用 AI 辅助编程开发，后续维护也将采用同样的方式。
