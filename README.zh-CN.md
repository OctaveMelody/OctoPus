# 章鱼简谱

[English](README.md) | **简体中文**

**章鱼简谱：玩转八度，轻松制谱。**

章鱼简谱是一款简谱桌面编辑器。乐谱使用 JPS（Jianpu Script）编写，编辑时可实时查看 SVG 预览。程序也能将简谱图片和 PDF 转成可编辑的 JPS 草稿，并将乐谱导出为 SVG、PDF、PNG 或 JPEG。

## 项目背景

章鱼简谱采用[番茄简谱](http://zhipu.lezhi99.com)的 JPS 格式，自行解析并渲染乐谱，力求与番茄简谱的显示效果一致。程序还支持在 6/8、9/8 和 12/8 拍号下自动分组音符，也能识别图片和 PDF 中的简谱。

## 功能

- 编辑 JPS，并实时预览乐谱。
- 将 JPG、PNG 简谱图片或 PDF 转成可编辑的 JPS 草稿。
- 将乐谱导出为 SVG、PDF、PNG 或 JPEG；PNG 和 JPEG 支持 96 和 300 DPI。
- 可在普通布局和转录布局之间切换。

## 下载与安装

请从[章鱼简谱 GitHub 官方发布页](https://github.com/OctaveMelody/OctoPus/releases)直接下载最新版，
并选择适用于你操作系统的安装包。

- **Windows：** 下载安装程序 `OctoPus_<版本>_x64_win64_setup.exe`，或便携 ZIP
  `OctoPus_<版本>_x64_win64_portable.zip`。Windows 需要 WebView2；多数系统已安装。PDF 转录
  还需要在 PATH 中安装 Poppler 工具，详见[环境说明](ENVIRONMENT.zh-CN.md)。
- **macOS 26 或更高版本（Apple Silicon）：** 下载并打开 `OctoPus_<版本>_arm64_macos.dmg`，将
  **章鱼简谱**拖入「应用程序」文件夹。该应用尚未使用 Apple Developer ID 签名或公证，因此首次启动时，Gatekeeper
  可能会阻止打开并显示应用已损坏的警告。将应用复制到「应用程序」后，打开「终端」并运行：

  ```bash
  sudo xattr -cr /Applications/OctoPus.app
  ```

  该命令会递归清除 app 包的扩展属性，其中包括触发 Gatekeeper 拦截的隔离标记。请仅对从 GitHub
  官方发布页下载的应用运行此命令，然后从「应用程序」启动章鱼简谱。
- **Linux：** 从发布页下载章鱼简谱 AppImage，赋予可执行权限后运行：

  ```sh
  chmod +x OctoPus_*_linux.AppImage
  ./OctoPus_*_linux.AppImage
  ```

## 识谱

章鱼简谱使用 RapidOCR 和 ONNX Runtime 将图片和 PDF 转成 JPS 草稿。较小、模糊或重叠的符号可能漏识或误识，使用前请对照原稿检查。音符编号识别结果的一致率较低，或草稿与原稿差异明显时，程序会提示复查。点击提示可查看对应的原稿区域；如果能关联到具体音符，也会定位到该音符。

## 后续计划

- 增加音频播放，以及 MIDI 导入/导出。
- 支持 MusicXML 导入/导出。
- 导出 LilyPond 源码文件。
- 为生成的乐谱增加颜色支持。
- 持续提升图片和 PDF 的识谱准确率，并可选择使用大语言模型辅助。

## 用户手册

可在程序中打开**帮助 → 快速上手**阅读简短入门指南，或打开**帮助 → 用户手册**查看完整参考。快速上手指南提供[英文版](docs/QUICKSTART.md)和[简体中文版](docs/QUICKSTART.zh-CN.md)。[中英文离线手册](docs/user-manual/index.html)介绍编辑流程、支持的 JPS 记谱方式和当前限制，并随发布包提供，包括 Windows 便携 ZIP 和 Linux AppImage。另有[英文 PDF](docs/PDF/OctoPus-User-Manual-en.pdf)和[中文 PDF](docs/PDF/OctoPus-User-Manual-zh-CN.pdf)。

JPS 格式规范见 [Tomato JPS Spec](https://github.com/yetist/jianpu-spec)。章鱼简谱的 JPS 输入遵循该规范。

## 字体

Windows 和 Apple Silicon macOS 桌面版优先使用系统中已安装的首选字体；缺少首选字族时，会改用兼容的已安装字体。可通过**帮助 → 字体状态**查看官方安装说明或重新检查。这两个平台的桌面包不包含程序的 13 种乐谱字体。Linux AppImage 使用随程序提供并经过验证的乐谱字体集。

## 源码构建

运行环境和各平台构建命令请参阅[环境说明](ENVIRONMENT.zh-CN.md)。生产构建使用锁定版本的
Python、Node/npm、Rust 和 Tauri CLI。在仓库根目录运行配置脚本：

```sh
python3 scripts/setup.py
```

Linux 构建还需要 GTK/WebKit 开发包和 Poppler 工具，详见
[Linux 系统依赖](ENVIRONMENT.zh-CN.md#linux-系统依赖包)。请在目标操作系统上构建；Python 引擎不支持交叉编译。

在 Linux 上本地构建 AppImage：

```sh
python3 scripts/build_portable.py --bundles appimage
```

在 Windows 上构建便携版：

```powershell
py scripts\build_portable.py
```

## 运行 Windows 便携版

在 Windows 上运行 `dist/<target>/portable/` 中的 `octopus.exe`。请保留完整的便携版目录，其中包含程序资源、Python 引擎和示例乐谱。Windows 需要 WebView2。

## 免责声明

章鱼简谱根据 GNU 通用公共许可证第 3 版发布。本软件免费提供，作者不作任何担保，也不对因使用本软件造成的直接或间接损失承担责任。

本项目的开发和后续维护会使用 AI 辅助工具。
