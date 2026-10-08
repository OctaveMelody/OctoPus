# 应用字体

[English](README.md) | **简体中文**

设置面板提供 HeiTi-1、HeiTi-2、SongTi、KaiTi 和 FangSong。每个已安装的系统字族在各操作系统上独立优先使用；缺失的字族改用其内置替代字体。Windows/macOS 采用下表映射。Linux（包括生产便携版）通过 fontconfig 精确匹配，优先使用与 Windows 相同的 Microsoft 字族；fontconfig 或对应字族不可用时，使用内置替代字体。源码/调试参考构建同样优先使用已安装的对应 Microsoft 字体。

| 角色 | Windows | macOS | 内置常规字面 |
| --- | --- | --- | --- |
| HeiTi-1 | Microsoft YaHei | PingFang SC | MiSans v4.009 |
| HeiTi-2 | SimHei | Heiti SC | LXGW Neo XiHei v1.305 |
| SongTi | SimSun | Songti SC | SimZhiSong v1.103 |
| KaiTi | KaiTi | Kaiti SC | LXGW WenKai v1.522 |
| FangSong | FangSong | STFangsong | Zhuque Fangsong v0.212 |

已保存的 HeiTi 仍作为 HeiTi-2 的别名。新文档使用 HeiTi-1/Bold。既有音符预设保持 Regular/Italic/Bold（a/c/b）；旧值与未改动的设置仍可读取。五个替代字族只提供常规字面，不提供合成字重。Noto Sans/Serif 的 regular/bold 用于补齐缺字；Liberation Sans 四个样式覆盖拉丁文/Arial。共内置十三个 TTF 字面，附带十份声明/许可证。Zhuque 为上游的技术预览版发布；其未修改的字族实际名称是 Zhuque Fangsong (technical preview)，缺字使用 Noto 备份。

系统字体文件保留在各自主机上，OctoPus 从不重新分发或安装它们。macOS 字体集合检查会选择请求的字族和最接近的字重，而不是集合中的第一个字面。预览和原生导出保留受支持的系统字体，包括 CFF 轮廓。Python 的 ReportLab PDF 路径无法嵌入 CFF；该路径显式使用对应的内置替代字体。TrueType 集合中的字面会为 Python PDF 注册而临时提取，不修改其元数据或轮廓。FontTools 4.60.2 支持集合检查；原生导出在各主机上加载主机字体及全部内置字面。PDF 嵌入文本字体；JPG 只包含像素。外部 SVG 查看器需要请求的字体可用。不会全局安装或替换任何字体。

WenKai、Noto、Zhuque 和 Liberation 使用 OFL 1.1。Neo XiHei/SimZhiSong 使用 IPA Font License 1.0；[原始 IPA 恢复说明](licenses/IPA-RESTORATION.txt)有文档记录。MiSans 使用小米自有许可，允许在应用中署名并保留声明后使用；它不是 OFL，不得修改或作为字体软件单独分发。应用“关于”面板致谢了小米 MiSans；其未修改的字体和完整官方协议（PDF 及提取文本）随应用附带，原始名称/二进制文件/声明均予保留。Noto 静态字重 400/700 由 FontTools 4.60.2 生成，不使用保留名称 Source。

sources.json 固定来源/归档哈希、成员、版本和声明；manifest.json 记录字面/许可证哈希及共享字族覆盖。在生产环境独立验证：

```sh
python3 build_desktop_engine.py --verify-fonts
```

下载、解包和再生成属于开发支持工作，在 OctoPus-dev 中运行：

```sh
uv run --no-sync --with zstandard==0.25.0 python tools/prepare_release_fonts.py
```

该脚本面向 ../OctoPus/src/octopus/assets/fonts，并把固定的来源缓存在被 Git 忽略的 OctoPus-dev/build/font-sources/ 中。生产构建只验证/使用已提交的输入，不需要开发仓库或下载脚本。工作进程、原生导出器、wheel 和前端都消费同一套规范的生产资产与完整声明。OCTOPUS_FONT_PROFILE=release 为源码检查启用生产字体策略；冻结的工作进程始终使用生产策略，即使提供了参考覆盖。

发布替代与备份字体是外部文件，由预览和导出共享。Linux：`usr/lib/OctoPus/fonts`；Windows：可执行文件旁的 `lib/Octopus/fonts`。macOS 资源映射为 `Contents/Resources/lib/Octopus/fonts`（原生构建待支持）。请将这些文件及其许可证声明与程序一起保留。系统字体优先策略不变。
