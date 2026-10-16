# 应用字体

[English](README.md) | **简体中文**

页面设置提供 HeiTi-1、HeiTi-2、SongTi、KaiTi 和 FangSong 等乐谱字体角色。桌面版本根据构建平台自动选择字体来源；用户不必在偏好设置中选择系统字体或内置字体。

- Windows 和 macOS 桌面版使用下表中各角色对应的首选已安装字族。首选字族不可用时，程序会查找兼容的已安装字体并提供官方安装说明。这些桌面包不包含程序的 13 种乐谱字体。
- Linux 生产便携版和 AppImage 直接使用下表中经过验证的内置字族，不受系统中冲突字体影响。Noto 字体用于补齐缺失字形。
- 源码/参考及 Python/CLI 配置保留仓库内字体资源，供开发和命令行导出使用；这与冻结的 Windows/macOS 桌面工作进程不同。

离线手册单独附带少量 regular/bold Noto Sans SC 子集，以便无网络阅读中文文档。PDF.js 标准字体也单独存在，仅用于导入 PDF 的查看，不属于乐谱字体。

| 角色 | Windows 首选已安装字族 | macOS 首选已安装字族 | Linux 内置常规字面 |
| --- | --- | --- | --- |
| HeiTi-1 | Microsoft YaHei | PingFang SC | MiSans v4.009 |
| HeiTi-2 | SimHei | Heiti SC | LXGW Neo XiHei v1.305 |
| SongTi | SimSun | Songti SC | SimZhiSong v1.103 |
| KaiTi | KaiTi | Kaiti SC | LXGW WenKai v1.522 |
| FangSong | FangSong | STFangsong | Zhuque Fangsong v0.212 |

已保存的 HeiTi 仍作为 HeiTi-2 的别名。新文档使用 HeiTi-1/Bold。既有音符预设保持 Regular/Italic/Bold（a/c/b）；旧值与未改动的设置仍可读取。五个 Linux 角色字族只提供常规字面，不提供合成字重。Noto Sans/Serif 的 regular/bold 用于补齐缺字；Liberation Sans 四个样式覆盖拉丁文/Arial。源码资源集中保留十三个 TTF 字面和十份声明/许可证；Linux 发布包包含这套乐谱字体。Zhuque 为上游的技术预览版发布；其未修改的字族实际名称是 Zhuque Fangsong (technical preview)，缺字使用 Noto 备份。

系统字体文件保留在各自主机上，OctoPus 从不重新分发或安装它们。macOS 字体集合检查会选择请求的字族和最接近的字重，而不是集合中的第一个字面。桌面原生导出保留受支持的已安装字体，包括 CFF 轮廓；Linux 导出使用经过验证的内置字面。Python 源码/CLI ReportLab PDF 路径无法嵌入 CFF，使用对应源码配置的替代字体。TrueType 集合中的字面会为 Python PDF 注册而临时提取，不修改其元数据或轮廓。FontTools 4.60.2 支持集合检查。原生 PDF 嵌入文本字体；JPG 只包含像素。外部 SVG 查看器需要请求的字体可用。不会全局安装或替换任何字体。

WenKai、Noto、Zhuque 和 Liberation 使用 OFL 1.1。Neo XiHei/SimZhiSong 使用 IPA Font License 1.0；[原始 IPA 恢复说明](licenses/IPA-RESTORATION.txt)有文档记录。MiSans 使用小米自有许可，允许在应用中署名并保留声明后使用；它不是 OFL，不得修改或作为字体软件单独分发。应用“关于”面板致谢了小米 MiSans；其未修改的字体和完整官方协议（PDF 及提取文本）随应用附带，原始名称/二进制文件/声明均予保留。Noto 静态字重 400/700 由 FontTools 4.60.2 生成，不使用保留名称 Source。

sources.json 固定来源/归档哈希、成员、版本和声明；manifest.json 记录字面/许可证哈希及共享字族覆盖。在生产环境独立验证：

```sh
python3 build_desktop_engine.py --verify-fonts
```

下载、解包和再生成属于开发支持工作，在 OctoPus-dev 中运行：

```sh
uv run --no-sync --with zstandard==0.25.0 python tools/prepare_release_fonts.py
```

该脚本面向 ../OctoPus/src/octopus/assets/fonts，并把固定的来源缓存在被 Git 忽略的 OctoPus-dev/build/font-sources/ 中。生产构建只验证/使用已提交的输入，不需要开发仓库或下载脚本。源码工作进程、导出器和 wheel 根据所选配置使用规范资源。Linux 桌面预览从原生管理的资源目录加载字体；Windows/macOS 冻结前端不含乐谱字体。`OCTOPUS_FONT_PROFILE=release` 为源码检查启用 Linux 发布策略；冻结工作进程始终使用其目标平台的生产策略，即使提供了参考覆盖。

经过验证的 Linux 乐谱字体集位于工作进程旁的 `usr/lib/OctoPus/fonts`，并附带清单和完整许可声明。请保留完整 Linux 便携版目录。Windows/macOS 桌面包不打包这些程序乐谱字体；原生字体解析器使用系统已安装字体及兼容的已安装替代字体。源码/CLI 配置仍需要仓库内字体资源。不要根据旧安装遗留的字体目录推断当前打包策略。
