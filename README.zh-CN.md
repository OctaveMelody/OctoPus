# OctoPus by OctaveMelody

[English](README.md) | **简体中文**

OctoPus 是一款桌面简谱编辑器，支持实时 SVG 预览、将图片和 PDF 转录为可校对的草稿，
以及导出 SVG、PDF 和 JPEG。目前尚不支持 LilyPond 转换。

本生产仓库包含应用源码、打包配置、离线 Python 引擎和 JPS 示例，可独立构建，
无需依赖开发仓库 OctoPus-dev。测试、审计、参考输出和开发工具保留在开发仓库中。

## 环境准备

[环境说明](ENVIRONMENT.md) 定义了独立的运行和构建环境。
安装 Python 3.11+、uv、Node.js 20.19+（含 npm）、Rust 1.92+ 和 Tauri CLI 2.11.5，然后运行：

```sh
python3 scripts/setup.py
```

Linux 原生构建还需要 GTK/WebKit 开发包和 Poppler 工具，详见
[Linux 环境依赖](ENVIRONMENT.md#linux-host-packages)。构建过程通过 uv 准备 Python 3.12
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

## 字体和示例

字体选项为黑体-1（HeiTi-1）、黑体-2（HeiTi-2）、宋体、楷体和仿宋。
Windows 分别优先使用 Microsoft YaHei、SimHei、SimSun、KaiTi、FangSong；
macOS 分别优先使用 PingFang SC、Heiti SC、Songti SC、Kaiti SC、STFangsong。
每种系统字体缺失时分别使用内置 MiSans Regular、Neo XiHei、SimZhiSong、
WenKai Regular、Zhuque Fangsong。Linux 生产版也优先使用已安装的上述微软字体，
通过 fontconfig 精确匹配；缺失时使用内置替代字体。便携版遵循相同规则。
旧 HeiTi 设置仍对应 HeiTi-2；Noto 补充缺失字符，Liberation Sans 替代 Arial 西文。
PDF 会嵌入字体，JPEG 保存像素；外部 SVG 查看器需要相应字体。
[字体指南](src/octopus/assets/fonts/README.md) 说明许可证、macOS 字体集合选择、
Python PDF 的 CFF 替代及原始 IPA 字体恢复方法。关于窗口注明小米 MiSans，
软件附完整小米许可协议；Zhuque v0.212 为上游技术预览版本。

音符样式仍为常规（Regular）、斜体（Italic）、粗体（Bold）。未修改的旧设置保持兼容。

开发参考测试使用系统中已安装的微软字体。生产版也优先使用配置对应的系统字体；
字体缺失时使用内置替代字体，其字形尺寸和像素结果可能不同。
生产仓库不包含微软字体文件。
`samples/jps_files/` 用于打包示例；`samples/jps_files_pretty/` 保留额外的源文件。
