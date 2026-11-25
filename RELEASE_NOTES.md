# ChronoView V1.0 正式版

本次以完成稳定性修复的当前版本替换此前 V1.0 发布，软件显示版本仍为 V1.0，内部版本为 1.0.0。

## 下载

- 安装版：`ChronoView-1.0.0-setup-win64.exe`，按当前用户安装。
- 绿色版：`ChronoView-1.0.0-portable-win64.zip`，完整解压后运行 `ChronoView.exe`，保留 `_internal` 和 `licenses`。
- 第三方源码及重链接材料：`ChronoView-1.0.0-third-party-sources.zip`。
- 校验：`ChronoView-1.0.0-SHA256SUMS.txt`。

固定播放器 DLL 与已验收的程序包保持一致，不需要另装 Python、FFmpeg 或播放器。

## 本次变化

- 保留照片/视频混合时间排序、年月导航、递归扫描、深浅主题和现有界面；侧栏底部集中到齿轮设置入口。
- 修复后台任务取消与退出、缩略图信号生命周期、旧播放事件干扰和错误视频仍可能继续发声的问题。
- 查看器复用 libmpv 原生实例，关闭时停止并静音，软件退出或清除记录时彻底释放；保留 D3D11 和 auto-safe 硬解方案。
- 图片按显示尺寸先加载预览，放大或查看原始尺寸时补载原图细节。
- 使用磁盘卷身份与相对路径区分照片库，避免同盘符不同硬盘误恢复索引或封面。
- 缩略图缓存默认 5 GiB，支持 LRU、过期/损坏/临时文件清理和低空间降级；设置提供确认清理缓存或本地记录的功能。
- 隐私页、迟到任务、日志脱敏和任务栏预览处理得到完善。隐私页用于防误展示，不是加密或安全访问控制。

## 实际验证

- Windows 原生回归：169 项通过，1 项因当前系统无法创建超长路径测试目录而跳过。
- 生成媒体完成 500 次混合切换、100 次查看器开关，媒体 SHA-256 保持一致。
- 完成 1 万、10 万、50 万模拟媒体记录压力测试，以及 24MP 图片预览/原图内存比较。
- 合成 H.264 1080p60、H.265 4K30 Main10 和强制软件解码短片播放至结束，播放器报告渲染/解码丢帧均为 0。
- 安装版、绿色版通过媒体、设置、隐私与本地数据清理验证；安装/重复安装/卸载保留非受管文件、双实例正常退出及进程残留检查通过。

## 边界

真实 USB 拔盘、长期运行、显存、不同显卡/驱动、听感音视频同步及实际任务栏悬停等尚未完成全面验证。底层反复重新创建原生实例仍有少量 Semaphore 句柄增长，常规查看路径已使用实例复用规避。HEIC/HEIF 解码器未随包提供，程序和安装包未代码签名。

详细方法、性能前后对比和未验证项见 [STABILITY_REPORT.md](STABILITY_REPORT.md)、[VALIDATION.md](VALIDATION.md)。稳定性报告中的“未推送”描述本地验收阶段；随后经用户授权，当前版本以 V1.0 正式发布。

This software uses FFmpeg under the LGPLv2.1 or later. Matching sources, native build information, notices and relinking materials are provided in the third-party source companion.
