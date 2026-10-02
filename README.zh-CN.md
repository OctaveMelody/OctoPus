# OctoPus — Oct（Octave，八度）+ Pus（JianPu，简谱）：全能简谱编辑器

[English](README.md) | **简体中文**

OctoPus 是一款桌面简谱编辑器，支持实时 SVG 预览、将图片和 PDF 转录为可校对的草稿，
以及导出 SVG、PDF 和 JPEG。

本生产仓库包含应用源码、打包配置、离线 Python 引擎和 JPS 示例，可独立构建，
无需依赖开发仓库 OctoPus-dev。测试、审计、参考输出和开发工具保留在开发仓库中。

## 功能

- 使用 JPS（Jianpu Script，简谱脚本）编辑简谱，并实时预览 SVG 乐谱。
- 在 6/8、9/8、12/8 中按附点四分音符拍自动连接减时线；可用 JPS `~`、`^`
  自定义连接与拆分。
- 通过文件选择器或将单个文件拖入原始图片/PDF 面板，导入 JPG/PNG/PDF 参考资料，
  再转录为可校对的 JPS 草稿。
- 将渲染后的乐谱导出为 SVG、JPEG 或 PDF。

## 转录草稿

识别支持较小的上下排列拍号及轻微倾斜的音符行。音符行附近清晰可见的
`p`、`pp`、`mp`、`mf`、`f`、`ff`、`rit` 和 `dim` 标记可转录为 JPS 装饰记号；
延长记号使用 `&yc`。`cres`、`cresc`、`crescendo` 和 `decrescendo` 等文字保留为
带引号的 JPS 注释。图形渐强、渐弱记号可附着在音符或延时横线上。

所有转录结果仍是需要校对的草稿。请对照原始乐谱检查歌词、节奏、八度点、声部分组，
以及每个装饰记号对应的音符或延时横线。较小、模糊或拥挤的标记仍可能遗漏或误识别。

## 计划改进

- 提高转录准确率。
- 导出 LilyPond 源码和 MusicXML。
- 导入 MusicXML 并转换为 JPS。
- 导入五线谱图片或 PDF，通过识别转换为 JPS。

以上项目尚在计划中；目前图片/PDF 转录生成的是需要人工校对的简谱草稿。

## 用户手册

在程序中选择 **帮助 → 用户手册**，或打开[中英文离线手册](docs/user-manual/index.html)。
手册涵盖界面操作、支持的 JPS 记谱、当前限制及计划，提供语言标签页，并随安装包和便携版附带。
另有对应[英文 PDF](docs/PDF/OctoPus-User-Manual-en.pdf) 和
[中文 PDF](docs/PDF/OctoPus-User-Manual-zh-CN.pdf)。

## 环境准备

[环境说明](ENVIRONMENT.zh-CN.md) 定义了独立的运行和构建环境。
安装 Python 3.11+、uv、Node.js 20.19+（含 npm）、Rust 1.92+ 和 Tauri CLI 2.11.5，然后运行：

```sh
python3 scripts/setup.py
```

Linux 原生构建还需要 GTK/WebKit 开发包和 Poppler 工具，详见
[Linux 环境依赖](ENVIRONMENT.zh-CN.md#linux-系统依赖包)。构建过程通过 uv 准备 Python 3.12
和锁定版本的引擎构建依赖。请在目标操作系统上构建；Python 引擎不支持交叉编译。

## 构建

在本仓库根目录下进行 Linux 构建：

```sh
python3 build.py --bundles deb
```

Windows 请使用原生 Windows 构建环境：

```powershell
python build.py --bundles nsis
# 或：python build.py --bundles msi
```

每次构建都会在 `dist/<Rust target triple>/` 下生成安装包和经过验证的便携版应用。
原生程序、前端和引擎的临时构建文件保存在 `build/` 下。两个目录均由 Git 忽略。
即使请求其他安装包类型，Linux 构建也会生成 Debian 包，以提供便携版所需的资源布局。

## 运行便携版

Linux x86_64：

```sh
./dist/x86_64-unknown-linux-gnu/portable/usr/bin/octopus
```

Windows：运行 `dist/<Rust target triple>/portable/octopus.exe`。
请保留完整的便携版目录，其中包含引擎和 65 个乐谱示例。
Linux 仍需要系统中的 GTK/WebKit 运行库和 Poppler 工具；Windows 需要 WebView2。
便携版已包含 Python 引擎，无需另行安装 Python。
上一次成功生成的便携版保留在 `portable.previous/` 下。

## 字体

发行版替代和备份字体为独立文件，预览及导出共同使用。Linux 位于
`usr/lib/OctoPus/fonts`，Windows 位于可执行文件旁的 `lib/OctoPus/fonts`；
macOS 资源配置为 `Contents/Resources/lib/OctoPus/fonts`（原生构建仍待支持）。
请保留字体及其许可证文件，操作系统字体优先策略保持不变。

每种字体选项优先使用已安装的对应系统字体；缺失时使用内置替代字体，生产便携版也遵循
相同规则。Linux 通过 fontconfig 精确查找 Windows 优先字体；没有精确匹配或没有
fontconfig 时，使用内置替代字体。

| 字体选项 | Windows / Linux 系统优先字体 | macOS 系统优先字体 | 内置替代字体（Fallback） | 内置缺字备用字体（Backup） |
| --- | --- | --- | --- | --- |
| HeiTi-1 黑体-1（默认） | Microsoft YaHei（微软雅黑） | PingFang SC（苹方） | MiSans Regular | Noto Sans SC → Noto Serif SC |
| HeiTi-2 黑体-2 | SimHei（黑体） | Heiti SC（黑体） | LXGW Neo XiHei | Noto Sans SC → Noto Serif SC |
| SongTi 宋体 | SimSun（宋体） | Songti SC（宋体） | SimZhiSong | Noto Sans SC → Noto Serif SC |
| KaiTi 楷体 | KaiTi（楷体） | Kaiti SC（楷体） | LXGW WenKai Regular | Noto Sans SC → Noto Serif SC |
| FangSong 仿宋 | FangSong（仿宋） | STFangsong（华文仿宋） | Zhuque Fangsong Regular | Noto Sans SC → Noto Serif SC |

备用字体用于补充缺字，并非另一组可选字体。当内置字体不包含某个文本元素所需的字符时，
渲染器先检查 Noto Sans SC 是否覆盖整段文字，再检查 Noto Serif SC。两者都无法完整覆盖时，
最终仍请求 Noto Sans SC，因此不能保证所有字符均有字形。Noto 黑体和宋体各含常规及粗体。
西文 **Arial** 请求使用内置 **Liberation Sans**，包含常规、斜体、粗体及粗斜体。

音符样式为**常规（Regular）、斜体（Italic）、粗体（Bold）**。旧 `HeiTi` 设置仍对应
HeiTi-2；未修改的旧设置保持兼容。开发参考测试使用已安装的微软字体；生产版也优先使用
对应系统字体，缺失时内置替代字体的字形尺寸和像素结果可能不同。软件不附带、安装或分发
微软字体文件。

打开**偏好设置**可切换界面语言，并为每类字体选择系统字体或内置替代字体。缺失的系统
字体选项会变灰，并自动使用内置替代字体。设置保存在本机，适用于预览与 SVG/PDF/JPG
导出，不修改保存的乐谱。

PDF 导出会嵌入字体，JPEG 保存像素；外部 SVG 查看器需要相应字体。若系统字体采用 Python
ReportLab 无法嵌入的 CFF 轮廓，该 Python PDF 导出路径会使用对应内置替代字体。详见
[字体指南](src/octopus/assets/fonts/README.md)及其许可说明。程序注明小米 MiSans，并附完整
小米许可协议；Zhuque v0.212 为上游技术预览版本。所有内置字体的许可与说明均予保留。

## 仓库内容

- `src/octopus/` 和 `ui/`：应用源码及离线 Python 引擎。
- `docs/user-manual/index.html`：随软件附带、可切换中英文标签页的用户手册。
- `samples/jps_files/`：65 个打包乐谱示例。
- `samples/jps_files_pretty/`：额外的源文件。
- `OctoPus-dev`（独立仓库）：测试、审计、参考输出和开发工具。
