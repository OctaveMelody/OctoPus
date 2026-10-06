# OctoPus — 简谱编辑与识谱工具

[English](README.md) | **简体中文**

OctoPus 是一款桌面简谱编辑器。写谱时可以实时预览；也可以把简谱图片或 PDF 识别成
可继续修改的 JPS 草稿，并导出为 SVG、PDF、PNG 或 JPEG。
无论是整理练习曲谱、准备一份方便分享的简谱，还是从照片开始录谱，都可以在 OctoPus
里继续修改和校对。

## 项目缘起

OctoPus 最初参考[番茄简谱](http://zhipu.lezhi99.com)显示出来的谱面，自行实现 JPS 解析
和排版。番茄简谱用脚本写谱很方便，但没有公开源码，无法直接改进原软件。OctoPus 还增加了
6/8、9/8、12/8 等拍号下的音符自动分组，以及从图片或 PDF 识别简谱的功能。
识别出的乐谱可以继续修改、校对和导出。

本生产仓库包含应用源码、打包配置、离线 Python 引擎和 JPS 示例，可独立构建，
不依赖开发仓库 OctoPus-dev。测试、审计、参考乐谱和开发工具放在开发仓库中。

## 功能

- 用 JPS（Jianpu Script，简谱脚本）编写和修改乐谱，边写边看实时预览。
- 在 6/8、9/8、12/8 等拍号中按附点四分音符拍自动分组音符；也可用 JPS `~`、`^`
  自己调整连接或拆分的位置。
- 从文件选择器导入 JPG、PNG、PDF 乐谱，或把文件拖到“原稿图片/PDF”面板，生成可校对的
  JPS 草稿。
- 导出 SVG、PDF、PNG 或 JPEG；PNG 和 JPEG 支持 96、300 DPI。
- 识谱时可点击原稿区域查看校对提示，也可随时取消正在运行的任务。
- 重新打开最近编辑过的乐谱、使用快捷键，或通过 Python 命令行批量导出整个文件夹。

## 识谱草稿与校对

识谱功能可以识别上下排列的拍号和略微倾斜的音符行。音符附近清楚可见的力度和表情记号
（`p`、`pp`、`ppp`、`mp`、`mf`、`f`、`ff`、`fff`、`rit`、`dim`）可写入 JPS 装饰记号；
延长记号使用 `&yc`。`cres`、`cresc`、`crescendo`、`decrescendo` 等文字会保留为带引号的
JPS 注释。图形渐强、渐弱线可以对应到音符，也可以对应到延时横线。图片和 PDF 识谱使用
RapidOCR + ONNX。

多声部大括号上方的简短伴奏数字，即使字号和主旋律接近，也可能识别为 `{bz ...}` 伴奏块。
较淡的减时线只有在附近也有明显笔画时才会识别。生成乐谱时，伴奏会和主旋律、其他声部
保持节拍一致并对齐。

识别结果只是草稿，请对照原稿检查歌词、节奏、音符上方或下方的八度点、声部分组，以及
装饰记号对应的是哪个音符或延时横线。小字、模糊或挤在一起的记号仍可能漏掉或认错。

程序会尽量排除乐谱区域外重复出现的页眉、页脚和页码。如果识别出的音符与原稿差异较大，
或生成的乐谱和原图明显对不上，程序会标出需要复查的位置。点击提示可查看原稿区域；如果
能确定对应音符，也会一并定位。提示可以帮你找到疑点，但不能保证识别完全正确。修改乐谱后，
之前的高亮会自动清除。

## 计划中的功能

- 提高图片和 PDF 识谱的准确率。
- 音频试听、MIDI 导出，以及 LilyPond/MusicXML 导出。
- 导入 MusicXML 并转换为 JPS。
- 导入五线谱图片或 PDF，识别后转换为 JPS。

这些功能还在计划中。目前图片/PDF 识谱生成的是简谱草稿，需要人工校对。

## 用户手册

在程序中选择 **帮助 → 用户手册**，也可以打开[中英文离线手册](docs/user-manual/index.html)。
手册介绍常用操作、支持的 JPS 写法、目前的限制和后续计划。手册随安装包和便携版附带，
还可查看[英文 PDF](docs/PDF/OctoPus-User-Manual-en.pdf)或
[中文 PDF](docs/PDF/OctoPus-User-Manual-zh-CN.pdf)。

## 环境准备

[环境说明](ENVIRONMENT.zh-CN.md)介绍了运行和构建所需的环境。如果你想从源码运行或打包，
请准备 Python 3.11+、uv、Node.js 20.19+（含 npm）、Rust 1.92+ 和 Tauri CLI 2.11.5，再运行：

```sh
python3 scripts/setup.py
```

Linux 桌面构建还需要 GTK/WebKit 开发包和 Poppler 工具，详见
[Linux 环境依赖](ENVIRONMENT.zh-CN.md#linux-系统依赖包)。构建工具会用 uv 准备 Python 3.12
及项目锁定的依赖。请在将要运行 OctoPus 的操作系统上构建；目前不支持跨系统打包。

## 构建

在仓库根目录运行以下命令，构建 Linux 安装包和便携版：

```sh
python3 build.py --bundles deb
```

Windows 请使用原生 Windows 构建环境：

```powershell
python build.py --bundles nsis
# 或：python build.py --bundles msi
```

构建完成后，安装包和通过资源检查的便携版会放在 `dist/` 下按系统区分的文件夹中。
临时构建文件保存在 `build/`。这两个目录已由 Git 忽略。Linux 构建会同时生成 Debian 包，
用于准备便携版所需的文件结构。

## 运行便携版

Linux x86_64：

```sh
./dist/x86_64-unknown-linux-gnu/portable/usr/bin/octopus
```

Windows：在生成的 `dist/` 文件夹中找到 `portable/`，运行里面的 `octopus.exe`。
请保留整个便携版目录；程序需要其中的引擎和 65 个乐谱示例。
Linux 仍需要 GTK/WebKit 运行库和 Poppler 工具；Windows 需要 WebView2。便携版已包含
Python 引擎，不用另外安装 Python。构建成功后，前一个版本会保留在 `portable.previous/`，
方便需要时回退。

## 字体

OctoPus 会优先使用电脑上已安装的字体；如果找不到对应字体，就使用程序附带的替代字体。
预览和导出使用相同的字体选择。请保留便携版中的 `fonts` 文件夹和字体许可证。

| 字体选项 | Windows / Linux 优先字体 | macOS 优先字体 | 内置替代字体 | 缺字补充字体 |
| --- | --- | --- | --- | --- |
| HeiTi-1 黑体-1（默认） | Microsoft YaHei（微软雅黑） | PingFang SC（苹方） | MiSans Regular | Noto Sans SC → Noto Serif SC |
| HeiTi-2 黑体-2 | SimHei（黑体） | Heiti SC（黑体） | LXGW Neo XiHei | Noto Sans SC → Noto Serif SC |
| SongTi 宋体 | SimSun（宋体） | Songti SC（宋体） | SimZhiSong | Noto Sans SC → Noto Serif SC |
| KaiTi 楷体 | KaiTi（楷体） | Kaiti SC（楷体） | LXGW WenKai Regular | Noto Sans SC → Noto Serif SC |
| FangSong 仿宋 | FangSong（仿宋） | STFangsong（华文仿宋） | Zhuque Fangsong Regular | Noto Sans SC → Noto Serif SC |

打开**偏好设置**可切换界面语言，并为每种字体选择系统字体或内置替代字体。电脑上没有
对应的系统字体时，该选项会变灰，并自动使用替代字体。设置保存在本机，应用于预览和
SVG、PDF、PNG、JPEG 导出，不会修改乐谱文件。

PDF 会嵌入字体，JPEG 保存为像素；在其他程序中打开 SVG 时，电脑也需要有对应字体。
更多字体和许可证说明见[字体指南](src/octopus/assets/fonts/README.md)。

<details>
<summary>字体替换和导出的补充说明</summary>

表格中的“缺字补充字体”只在当前字体不包含某些字符时使用，并不是另一项可选字体。
程序会先尝试 Noto Sans SC，再尝试 Noto Serif SC。若两者都缺字，显示效果仍无法保证。
Noto 黑体和宋体各包含常规、粗体；Arial 使用内置 Liberation Sans，包含常规、斜体、粗体和粗斜体。

音符样式支持常规、斜体和粗体。旧版 `HeiTi` 设置仍对应 HeiTi-2，原有设置继续可用。
开发环境的参考测试使用已安装的微软字体；生产版也会优先使用相应系统字体。替代字体的
字形尺寸和像素效果可能不同。软件不附带或分发微软字体。

如果系统字体使用 Python ReportLab 无法嵌入的 CFF 轮廓，Python PDF 导出会改用内置替代字体。
程序保留 MiSans 的小米许可证；Zhuque v0.212 为上游技术预览版本。所有字体许可证均随程序保留。

</details>

## 仓库内容

- `src/octopus/` 和 `ui/`：应用源码及离线 Python 引擎。
- `docs/user-manual/index.html`：随软件附带、可切换中英文标签页的用户手册。
- `docs/THIRD_PARTY_NOTICES.md`：OCR 模型、RapidOCR 与 ONNX Runtime 的第三方许可说明。
- `samples/jps_files/`：65 个打包乐谱示例。
- `OctoPus-dev`（独立仓库）：测试、审计、参考输出和开发工具。

项目采用 GPL-3.0-or-later 许可证；完整文本见 [LICENSE](LICENSE)，并随 Python 发行包和
桌面程序资源一起分发。
