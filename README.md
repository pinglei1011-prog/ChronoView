# ChronoView V1.1.0

Windows 本地照片与视频浏览器，Python + PySide6 编写。照片管理保留现有界面，视频播放改用 libmpv 0.42.0 原生窗口和 D3D11 硬件解码。无需安装 Python、系统播放器或 HEVC 扩展；媒体原文件只读。

[下载正式版：安装包、绿色版及配套源码](https://github.com/pinglei1011-prog/ChronoView/releases/tag/V1.1.0)。安装版适合日常使用，绿色版解压整个文件夹后运行 ChronoView.exe。不要只复制 EXE，须保留 _internal 和 licenses。

## 使用

- 启动直接进入主界面隐私页，主动打开照片库后才显示媒体；没有独立启动欢迎页。隐私页或 Ctrl+L 可随时隐藏照片、目录和统计，并停止查看器视频。它用于避免误展示，不提供密码、加密或缓存擦除。
- 全部照片显示照片与视频的完整混合列表，默认按文件名时间从旧到新；可切换从新到旧。左侧“全部照片 → 年份 → 月份”保留单击展开/收起，年份升序、月份升序；未识别日期仅有内容时出现。年份页面仍使用无封面的月份卡片。
- 缩略图下只显示日期时间，文件名和路径可悬停查看。单击选中，双击或 Enter 打开；视频打开并准备好后自动播放。视频封面中央有播放按钮，可读取时显示时长。
- 查看器左右键连续切换照片和视频，照片画布两侧及顶部提供导航按钮。照片可缩放、平移、适应窗口和原始尺寸查看；缩略图“完整/铺满”只改变预览方式。
- 视频画面单击暂停/继续，双击或 F11 全屏；支持进度拖动、音量、空格播放暂停、EOF 后重播。Esc 先退出全屏，再关闭查看器。
- F5 刷新、Ctrl+O 选择目录、Ctrl+B 切换侧栏。侧栏隐藏后网格利用可用宽度，日期在卡片下居中。深浅主题、卡片大小及是否记住照片库位置可调整。
- 递归扫描、SQLite 索引和缩略图缓存保留。主动打开已知库可从索引恢复；目录内容改变后按 F5，盘符变化时重新选目录。硬盘断开显示离线状态和读取提示，不修改原文件。

## 视频播放

默认使用 libmpv 原生子窗口，gpu-next / D3D11、auto-safe 硬件解码和 fast 渲染配置，避免将每帧视频回读到 Python/Qt。fast 配置减少部分缩放和画面处理以降低负载；不改变原始视频。打开查看器时暂停后台视频封面解码。

已加入错误提示、异步关闭、旧事件隔离和自动播放手势防误暂停。独立 DLL 加载失败时显示友好提示。可关闭全部窗口后使用随包的“兼容播放.cmd”改用 Qt 后端；该路径保留硬件解码，默认避开已定位的 GPU 纹理空指针路径。兼容模式的流畅度可能低于默认内核。

支持的文件后缀包括 MP4/MOV/MKV/AVI；实际测试范围和未测试能力见 [VALIDATION.md](VALIDATION.md)。HEIC/HEIF 解码器不包含在当前包中；缓存暂不自动清理。

## 安装与本机数据

安装版按当前用户安装，默认位于 `%LOCALAPPDATA%\Programs\ChronoView`，提供开始菜单入口、可选桌面快捷方式和卸载入口。绿色版和安装版使用相同程序内容。卸载不主动清理照片库、设置、索引或缓存。

设置使用 QSettings，通常位于 `HKCU\Software\ChronoView\ChronoView`。索引、日志和缩略图通常位于 `%LOCALAPPDATA%\ChronoView\ChronoView`；实际位置由 QStandardPaths 决定。`--settings-file` 可隔离测试设置及索引。日志可能包含本机媒体路径，反馈问题前可自行脱敏。

## 开发与构建

建议 Windows 10 22H2 / Windows 11 x64、Python 3.12。开发依赖见 requirements.txt / requirements-dev.txt。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup.ps1
.venv\Scripts\python.exe scripts\prepare_libmpv.py
.venv\Scripts\python.exe -m pytest -q
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build.ps1
.venv\Scripts\python.exe scripts\verify_portable.py
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_installer.ps1 -Compiler "C:\path\to\ISCC.exe"
.venv\Scripts\python.exe scripts\prepare_sources.py
.venv\Scripts\python.exe scripts\package_release.py
```

首次源码构建从本版本绿色包获取并验证固定 DLL；已有 vendor DLL 时只做 SHA-256 检查。重新编译播放内核见 scripts/native、固定源码锁及 .github/workflows/native-player.yml。配套源码包同时提供 native 构建记录、精确静态库重链接输入和对应 LGPL 源码。Inno Setup 编译器需另备；测试素材生成工具 imageio-ffmpeg 不进入运行包。

## 第三方许可

运行包 licenses 目录提供 Python、Pillow、Qt/PySide6、FFmpeg、libmpv 及静态依赖归属和许可证。libmpv 使用固定源码的 LGPL 构建（禁用 GPL/nonfree）；Qt 的视频封面及备用播放仍使用其随附 FFmpeg 动态库。源码、构建信息与静态重链接材料随同版本 third-party-sources.zip 发布。

兼容 DLL 可替换，路径及说明见 licenses/README-libmpv.txt；应用不额外限制为修改 LGPL 组件而进行的调试和逆向工程。编解码专利与开源许可是不同事项，本文不构成商业发行的法律认证。
