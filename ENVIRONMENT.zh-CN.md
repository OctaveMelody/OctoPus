# 生产版运行与构建环境

[English](ENVIRONMENT.md) | **简体中文**

本仓库可独立运行和构建。依赖清单、锁定文件、环境准备脚本和构建程序不得读取
OctoPus-dev 中的开发测试、审计依赖、行为说明或开发环境。

## 仓库结构

- `pyproject.toml`：Python 包元数据、依赖声明和可选依赖组。
- `uv.lock`：精确依赖版本；使用 `uv sync --locked` 实现可复现安装。
- `.python-version`、`.node-version`、`.npm-version`、`rust-toolchain.toml`：工具链版本。
- `scripts/`：可执行的环境准备辅助脚本。
- `.venv/`、`ui/web/node_modules/`：仓库内的依赖安装目录，由 Git 忽略。

`ENVIRONMENT.md` 及本中文版提供供人阅读的说明。本 uv 项目不需要另行维护
`requirements.txt`；依赖声明和锁定文件是依据。如需使用 pip 工具，可在本仓库根目录导出：

```sh
uv export --locked --extra transcription --no-emit-project --output-file /tmp/octopus-requirements.txt
```

导出文件只列出第三方依赖。在选定的虚拟环境中，另用
`python -m pip install --no-deps -e .` 安装本仓库。锁定文件变更后应重新导出。
参见 [uv 项目结构](https://docs.astral.sh/uv/guides/projects/)。

Linux 使用 `python3 scripts/setup.py`，Windows 使用 `py scripts/setup.py` 准备生产环境。准备
完成后，Linux 运行 `python3 scripts/build_portable.py`，Windows 运行
`py scripts/build_portable.py`。启动器会自行定位仓库和生产虚拟环境，也可在其他工作目录通过
完整脚本路径调用。这样源码侧检查与冻结引擎收集的依赖保持一致。

## 锁定依赖

- 原生引擎构建使用 Python 3.12（`.python-version`）；Python 源码支持 3.11+。
- Python 运行与导出依赖：`pyproject.toml` 和 `uv.lock`。
- OCR：`transcription` 可选依赖组提供唯一的本地离线 RapidOCR + ONNX 引擎，使用
  `rapidocr==3.9.2` 和 `onnxruntime==1.30.0`。工作进程和界面直接使用该引擎，不提供
  后端切换设置。
- 引擎冻结打包：`desktop-build` 可选依赖组，PyInstaller 6.22.3。
- Node.js 22.23.3（`.node-version`）、npm 10.9.9（`.npm-version`）；前端锁定文件为
  `ui/web/package-lock.json`。
- Rust 1.98.1（`rust-toolchain.toml`），Cargo 锁定文件为 `ui/Cargo.lock`。
- Tauri CLI 2.11.5：`cargo install tauri-cli --version 2.11.5 --locked`。
- 准备和验证这些锁定文件时使用 uv 0.12.21；uv 属于主机环境工具。

主机工具可全局安装，也可放在 PATH 中的工作区工具目录。Python `.venv`、前端
`ui/web/node_modules` 及全部 `build/`、`dist/` 输出属于本仓库，均由 Git 忽略。
全新克隆可直接使用已安装的常规主机工具，无需开发仓库。

## Linux 系统依赖包

Ubuntu/Debian 原生构建需要：

```sh
sudo apt-get update
sudo apt-get install -y build-essential pkg-config libwebkit2gtk-4.1-dev libgtk-3-dev \
  libayatana-appindicator3-dev librsvg2-dev poppler-utils
```

通过 Debian 包安装后，应用使用包管理器安装的 GTK/WebKit 运行库及 `poppler-utils`；
内置 Python 引擎无需另行安装 Python。请保留相邻的 engine/examples/docs 资源。
内置字体覆盖受支持的字体选项；开发仓库中的权威参考语料对比需要安装
Microsoft YaHei、SimHei、SimSun 和 Arial。替换字体会改变渲染结果，不能据此证明
与参考输出一致。

## 环境准备与源码运行

在本目录中，确认 uv、Node 和 Rust 可用后运行：

```sh
python3 scripts/setup.py
uv run --locked --extra transcription octopus render samples/jps_files/Symbols.jps --out-dir build/symbols
uv run --locked --extra transcription python -m ui.engine
```

引擎从标准输入逐行读取 JSON，并将响应写入标准输出。只需 Python 运行环境时，使用
`python3 scripts/setup.py --runtime-only`。可选 `pixel` 依赖组支持通过浏览器 DOM 导出 SVG，
需要执行 `uv run --extra pixel playwright install chromium`；该功能不打包进离线引擎。
本仓库的 Python 可选依赖组不包含 Pytest、Ruff、mypy 或开发验证资料。

## 批量导出与桌面引擎能力

生产 Python 命令行提供文件夹导出，不会覆盖已有文件：

```sh
uv run --locked octopus batch-export scores --out combined.pdf
uv run --locked octopus batch-export scores --out-dir exported --format pdf --recursive
uv run --locked octopus batch-export scores --out-dir images --format png --dpi 300
```

`ui.engine` 桌面握手提供仅检查语法的 `parse` 操作及 PNG 能力。转录先返回带请求标识、
大小受限的进度帧，最后返回一份结果。原生取消会停止独立转录进程树，并使待插入草稿失效；
预览进程独立。旧 HTTP/文件/恢复协议及审计入口仅保留在 OctoPus-dev，不进入生产分发包。

构建前设置 `VITE_UPDATE_CHECK_ENABLED=false` 可隐藏“帮助 → 检查更新”。默认仍显示此项；
该开关只改变菜单，不移除更新代码，也不改变版本号。

## 构建安装包

未明确指定类型的构建请求仅构建生产版，包括便携版可执行程序。只有明确要求时才构建
开发版可执行程序；开发版构建说明保留在支持仓库中。

Linux 运行 `python3 scripts/build_portable.py`；Windows 运行 `py scripts/build_portable.py`。
只有明确需要安装包时才在 Linux 使用 `--bundles deb`，或在 Windows 使用 `--bundles nsis`
或 `--bundles msi`。该启动器使用仓库锁定的环境；构建器会在编译前检查 Python、Node/npm、
Rust/Cargo、Tauri CLI 和系统依赖。它先构建前端与引擎，再调用 Tauri，并关闭本次调用中的
嵌套预构建钩子。Windows 需要 Microsoft C++ Build Tools 和 WebView2；Rust/PyInstaller
目标架构必须与运行 Python 的主机一致，不支持引擎交叉编译。macOS 打包暂未实现。

手动设置的应用版本是仓库根目录 `VERSION` 文件中的 SemVer 值，不带开头的 `v`。当前版本为
`1.0.0-beta`，对应已指定的 `v1.0-Beta`。发布时应有意更新 `VERSION`；Git 标签和当前时间
不会改变应用版本。`build.py` 会校验该值并注入 Tauri 和前端；`package.json` 和源码中的字面值
不是应用版本来源。

数字构建号为 OctoPus 产品仓库 `HEAD` 可达的提交数（`git rev-list --count HEAD`）。同时显示的
短 SHA 用于标识确切的产品提交。`build.py` 始终相对于脚本所在目录读取 Git 元数据，因此从
OctoPus-dev 调用生产构建脚本时，不会使用 OctoPus-dev 的提交数或 SHA；仅修改 OctoPus-dev
不会改变生产版本或构建标识。必须获取产品仓库完整 Git 历史；浅克隆会被拒绝，因为无法计算
完整提交数。产品工作树中的未提交更改可能改变二进制文件，却不会改变基于提交的标识；发布构建前请先提交产品代码。打包请使用 `scripts/build_portable.py`；直接调用 Tauri 会绕过版本和构建号生成。

`build.py` 在 `build/` 下构建前端、引擎和原生应用，将安装包复制到
`dist/<target-triple>/`。目录发布会对临时访问错误进行有限重试，必要时复制已验证的暂存文件，
并在失败时恢复上一个输出。引擎通过字形检查、协议握手及渲染冒烟测试后才替换原有输出。
每个仓库拥有独立的锁定文件；有意更新时使用 `uv lock`、npm 或 Cargo，并验证更新结果。

## 发布字体

锁定的字体资源及 OFL、IPA、小米 MiSans 许可证位于 `src/octopus/assets/fonts/`。
打包程序验证其哈希，并将字体用于引擎、预览和原生导出器。构建无需下载字体或安装
系统字体。参见[字体资源指南](src/octopus/assets/fonts/README.md)。
源码引擎默认使用参考字体；通过 `OCTOPUS_FONT_PROFILE=release` 启用发布版字体策略检查。
打包后的引擎和原生导出器按每种字体选项分别优先使用配置对应的已安装系统字体，缺失时
使用内置替代字体；生产便携版同样如此。参考字体文件不纳入 Git。
参见[字体对应表](README.zh-CN.md#字体)。

## 生产便携版测试

每次原生构建均在 `dist/<target-triple>/portable/` 下生成不纳入 Git 的便携版目录。只有
明确传入 `--bundles` 才会额外生成安装包。替换便携版前，构建程序会验证引擎、字体、字形资源、中文渲染、
示例文件内容及打包的用户手册。`portable.previous/` 保留上一次成功生成的便携版。

Linux 可从任意工作目录运行，以下路径按生产仓库根目录给出：

```sh
./dist/x86_64-unknown-linux-gnu/portable/usr/bin/octopus
```

Windows 运行 `dist/<target-triple>/portable/octopus.exe`。请保持便携版目录完整。
Linux 仍需要主机 GTK/WebKit 库和 Poppler 工具；Windows 需要 WebView2。
这是带应用本地资源的生产测试版本，并非静态打包整个操作系统运行环境。
`build/` 和 `dist/` 均由 Git 忽略。字体已内置，无需另外安装字体。

发布包不将替代字体嵌入可执行文件。Linux 资源位于 `usr/lib/OctoPus/`；
Windows 在 `octopus.exe` 旁使用 `lib/OctoPus/`；macOS 资源配置使用
`Contents/Resources/lib/OctoPus/`（macOS 原生构建仍待支持）。共享的 `fonts/`
目录包含所有替代及备份字体、清单和许可证，预览与 Python 导出共同使用。
请保持便携目录完整。默认仍优先使用操作系统字体，缺失或手动选择时使用免费替代字体。
打包 OCR 模型、RapidOCR 和 ONNX Runtime 的许可与归属说明见
[THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md)。
