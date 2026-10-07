# 八爪鱼简谱（OctoPus）

[English](README.md) | **简体中文**

八爪鱼简谱（OctoPus）是一款桌面简谱编辑器，以 JPS（Jianpu Script）作为乐谱源格式，可实时生成 SVG
预览。程序也支持将简谱图片和 PDF 识别为可编辑的 JPS 草稿，并导出为 SVG、PDF、PNG 或 JPEG。

当前“关于”显示版本为 **v1.0-Beta**，标语为“八爪鱼简谱：玩转八度，轻松制谱”。

## 项目背景

八爪鱼简谱采用[番茄简谱](http://zhipu.lezhi99.com)的 JPS 格式，独立实现解析和乐谱排版，
并以匹配其渲染输出为目标。程序增加了 6/8、9/8、12/8 拍号下的音符自动分组，以及图片和 PDF 识谱功能。

本生产仓库包含应用、打包配置、离线 Python 引擎和 JPS 示例。测试、审计、参考输出和开发工具
位于独立的 OctoPus-dev 仓库。

## 功能

- 编辑 JPS 乐谱，并实时预览排版结果。
- 在 6/8、9/8、12/8 拍号中按附点四分音符拍自动分组音符；可使用 JPS `~`、`^` 自定义连接与拆分。
- 将 JPG、PNG 和 PDF 乐谱图片识别为 JPS 草稿。识谱结果提供原稿区域提示，运行中的任务可取消。
- 导出 SVG、PDF、PNG 或 JPEG；光栅图像支持 96 和 300 DPI。
- 使用布局菜单选择普通或转录布局；各面板支持最大化、还原和关闭，关闭后保留内容。
- 使用快捷键，或通过 Python 命令行批量导出文件夹。

## 识谱

图片和 PDF 识谱使用 RapidOCR 与 ONNX Runtime。识别结果为待校对草稿，使用前应与原稿核对。
较小、模糊或相互重叠的记号可能遗漏或误识别。当音符编号匹配度较低，或渲染结果与原稿差异较大时，
程序会生成复查提示。提示可定位到相关原稿区域；在能够对应的情况下，也会定位到相应音符。

## 后续计划

- 提高图片和 PDF 识谱准确率。
- 增加音频试听、MIDI 导出，以及 LilyPond 和 MusicXML 导出。
- 支持导入 MusicXML 并转换为 JPS。
- 支持识别五线谱图片和 PDF 并转换为 JPS。

## 用户手册

在程序中选择 **帮助 → 用户手册**，或阅读[中英文离线手册](docs/user-manual/index.html)。手册介绍
编辑流程、支持的 JPS 记谱和当前限制，随安装包和便携版附带。另有[英文 PDF](docs/PDF/OctoPus-User-Manual-en.pdf)
和[中文 PDF](docs/PDF/OctoPus-User-Manual-zh-CN.pdf)。

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
Python 引擎和乐谱示例。Linux 需要 GTK/WebKit 运行库和 Poppler 工具；Windows 需要 WebView2。

## 字体

字体角色优先使用已配置的系统字体；系统字体不可用时，程序使用随附并保留许可证的替代字体。
可在**偏好设置**中配置字体。PDF 导出会嵌入字体；外部 SVG 查看器需要能够访问乐谱引用的字体。
字体对应关系、替换规则和许可证见[字体指南](src/octopus/assets/fonts/README.md)。

## 仓库内容

- `src/octopus/` 和 `ui/`：应用源码及离线 Python 引擎。
- `docs/user-manual/index.html`：随程序附带的中英文用户手册。
- `docs/THIRD_PARTY_NOTICES.md`：OCR 模型、RapidOCR 和 ONNX Runtime 的许可说明。
- `samples/jps_files/`：65 个打包乐谱示例。
- OctoPus-dev：测试、审计、参考输出和开发工具。

八爪鱼简谱采用 GNU 通用公共许可证第 3 版或后续版本（GPL-3.0-or-later），不附带任何质保。完整文本见 [LICENSE](LICENSE)，并随 Python 发行包和桌面程序资源分发。
