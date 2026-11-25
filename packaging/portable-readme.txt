ChronoView V1.1.0 正式版 — 2026/11/25

绿色版：完整解压后双击 ChronoView.exe，保留 _internal 和 licenses。
安装版：运行 ChronoView-1.1.0-setup-win64.exe，按当前用户安装，无需管理员权限。
不需要另装 Python、FFmpeg、mpv、系统播放器或 HEVC 扩展。

启动进入主界面隐私页，主动打开照片库后显示媒体；Ctrl+L 可隐藏媒体并停止视频。
全部照片显示所有照片和视频，默认从旧到新；侧栏按年份、月份浏览，单击展开收起。
单击缩略图选中，双击/Enter 打开；视频准备好后自动播放。
画面单击暂停/继续，双击/F11 全屏，Esc 返回；支持进度、音量、左右键切换。
照片支持缩放和平移。Ctrl+B 隐藏侧栏，F5 刷新，Ctrl+O 选择目录。
隐私页不是密码锁或加密，不清除已有索引和缩略图。
原始照片和视频只读，不修改、移动、重命名或删除。

默认内核 libmpv 0.42.0，D3D11 硬件解码，fast 渲染配置。
若设备存在兼容问题，关闭全部窗口后运行“兼容播放.cmd”切到 Qt 后端。
HEIC/HEIF 解码器未包含；新增文件按 F5，缓存暂不自动清理。
卸载安装版会保留用户设置、索引、缓存及照片库。

测试和已知边界见 VALIDATION.md，第三方归属、许可及 DLL 替换说明见 licenses。
配套源码/重链接包：ChronoView-1.1.0-third-party-sources.zip。
SHA-256：ChronoView-1.1.0-SHA256SUMS.txt。
下载与问题反馈：https://github.com/pinglei1011-prog/ChronoView/releases/tag/V1.1.0
