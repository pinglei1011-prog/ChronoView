# ChronoView

Windows 本地照片与视频浏览器，Python + PySide6 编写。**当前版本 V1.0（2026/11/25 更新）：采用当前新版界面，包含照片/视频浏览、年月导航和主界面隐私页。** 完全本地运行，不需要账号、网络或系统播放器，原始媒体只读访问。

## 启动

[下载 V1.0 绿色版](https://github.com/pinglei1011-prog/ChronoView/releases/tag/V1.0)。

开发环境双击 `run.cmd`，或执行 `.\.venv\Scripts\python.exe main.py`。

在项目目录可双击 `启动ChronoView.cmd` 启动正式程序；绿色版也可双击 `dist\ChronoView-1.0.0\ChronoView.exe`。复制到其他电脑时必须复制整个 `ChronoView-1.0.0` 文件夹，保留 `_internal`；不需要另装 Python、PySide6、FFmpeg 或 Windows HEVC 扩展。

1. 启动直接进入主界面，默认停在左侧的隐私页，不显示照片、年月/数量或目录路径，也不自动恢复索引。点击中间的打开上次照片库（无记录时为打开照片库），或左侧全部照片，开始浏览；选择文件夹也可打开其他目录。取消选目录仍停留当前页面。独立启动欢迎页已移除。
2. 自动递归扫描所有子目录，按文件名日期建立年份、月份相册；无效日期归入“未识别日期”。
3. 点击“全部照片”直接显示照片库所有照片和视频缩略图，包括未识别日期的文件，按文件名时间混合排序。左侧保留“全部照片 → 年份 → 月份”导航；点击年份显示该年的无封面月份卡片，点击月份显示对应媒体。年份从早到晚排列，月份从 1 月到 12 月，只显示有内容的月份。未识别日期分类仅在有内容时出现。返回按钮按“月份 → 年份 → 全部照片”返回，完整列表与月份列表默认从旧到新，可手动切换为从新到旧。
4. 缩略图下方只显示日期时间，完整文件名和路径可通过鼠标悬停提示查看。双击照片打开大图；单击视频直接播放。视频缩略图的播放按钮位于封面中央。选中项目后按 Enter 也可打开。
5. 查看器内左右键连续切换照片、视频；照片画布左右两侧中间也有上一项/下一项按钮，顶部入口继续保留。单击视频画面或按空格播放/暂停，视频可拖动进度、调整音量。照片可滚轮缩放、拖动平移、适应窗口和原始尺寸显示。
6. F11 或查看器按钮切换全屏，双击视频画面也可切换。Esc 先退出全屏，再次 Esc 关闭查看器。
7. F5 刷新照片库，Ctrl+O 重新选择文件夹。主题和缩略图大小会记住。
8. 点击侧边栏右上角按钮收起导航，照片网格自动使用更宽空间；点击主区域左上角按钮重新展开。Ctrl+B 也可切换，侧栏显示状态会记住。
9. 照片和视频使用统一大小的缩略图卡片，可选择“完整”保留全部画面，或“铺满”居中裁切填满方格；该选择不修改原图，打开大图仍显示完整画面。网格随窗口、侧栏和缩略图大小重新排版；返回按钮使用矢量图标和明确的目标名称，全部照片首页隐藏返回入口。

## 当前功能

- 支持 JPG/JPEG、PNG、WebP、BMP；照片按 EXIF 方向显示，缩略图不拉伸。
- MP4、MOV、MKV、AVI 纳入混合时间线，提取真实视频封面和可读取的时长；点击视频进入内置播放器。
- 采用 Qt Multimedia 的 FFmpeg 后端，绿色版自带动态解码库。已验证 H.264 MP4、H.265 MOV、H.264 MKV；AVI 已纳入格式支持但本次未专项验证。HDR、Dolby Vision、10-bit 及所有编码组合不作兼容性保证。
- 打开照片/视频查看器时暂停后台视频封面解码，关闭后恢复队列，避免 GPU 帧回读阻塞播放；已在运行的少量图片工作线程可继续完成。
- Windows + 当前 Qt 6.10.3 使用逐帧提交，减少视频窗口合并更新造成的漏绘；保留硬件解码和垂直同步。异常时可用绿色版中的“兼容播放.cmd”回到原方式，新旧窗口需先全部关闭。其他平台/Qt 版本自动沿用 Qt 默认路径。
- 视频切换释放前先解除旧音频通知连接，避免音频工作线程与 Python 回调锁相互等待。新播放器自动恢复音量/静音/设备通知。
- 视频播放、暂停、拖动进度、音量、全屏；切换项目时异步停止并销毁旧播放器，损坏/缺失文件显示友好提示。
- Qt Model/View 网格按可见区域申请缩略图；图片任务最多 3 个后台线程，视频封面最多 2 个异步解码器，总待处理请求最多 48，内存缩略图最多 192 张。
- 缩略图缓存键包含路径、文件大小和纳秒修改时间；视频时长作为 sidecar 保存，重复浏览可直接命中缓存。正常刷新后会重试读取失败的文件。
- 已知文件在索引保存后被修改时，首次读取会在后台使用文件当前的大小和修改时间生成缩略图，不会把索引过期误判成“无法读取”。真正读取失败时，悬停缩略图可查看原因，错误也记录到本机日志。
- SQLite 保存各照片库的完整路径、类型、文件名日期、大小、修改时间。完整成功扫描后按变更更新记录并移除已删除条目，取消/异常扫描不覆盖持久化快照。
- **启动停在主界面隐私页；主动打开照片库后优先从本地索引恢复，不自动完整扫描目录。新增、删除或修改文件后按 F5。** 手动刷新仍会递归枚举文件，尚无目录监视或文件系统日志级增量发现。
- 移动硬盘断开仍保留离线列表；重新连接后刷新即可。盘符变化后重新选择目录。
- 原始文件仅枚举和读取，不编辑、移动、重命名或删除，也不向照片库写入缓存或数据库。

HEIC/HEIF 仍为可选能力。本构建未安装解码器，需要时执行 `uv pip install --python .venv\Scripts\python.exe -r requirements-heif.txt` 后重构建，并用真实素材验证。

## 本机设置和数据

- 设置：QSettings，Windows 当前用户注册表 `HKEY_CURRENT_USER\Software\ChronoView\ChronoView`。
- 索引与日志：通常为 `%LOCALAPPDATA%\ChronoView\ChronoView\library.sqlite3` 和 `chronoview.log`。
- 缩略图：通常为 `%LOCALAPPDATA%\ChronoView\ChronoView\cache\thumbnails`。
- 具体位置由 QStandardPaths 决定，代码不硬编码开发机路径。`--settings-file` 为测试隔离选项，使用指定文件及其同级索引。

## 开发、测试、构建

建议 Windows 10/11 x64、Python 3.12。首次安装依赖需要网络，运行应用不需要网络。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup.ps1
.\.venv\Scripts\python.exe -m pytest -q
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build.ps1
.\.venv\Scripts\python.exe scripts\verify_portable.py
```

`scripts/verify_portable.py` 会生成临时真实视频，启动打包版进行照片、封面、播放控制及年月导航检查，结果保存到 `work/packaged-0.2.21-media.json`。`imageio-ffmpeg` 仅用于开发时生成测试素材，**不随应用打包**。

其他工具：`scripts/visual_check.py` 生成合成相册与深浅截图；`scripts/benchmark_index.py` 测量 2 万个合成文件的扫描/索引时间；`scripts/benchmark_playback.py` 只读对照帧信号、原生渲染提交和界面间隔；`scripts/verify_playback.py F:\photo` 用打包 EXE 只读检查真实文件，默认每个最多 8 秒、最多 12 个；`scripts/prepare_sources.py` 下载对应第三方源码形成配套源码包。

## 视频依赖与许可证

Qt / PySide6 6.10.3 与 Qt 随附 FFmpeg 7.1.3 动态库一起打包。已从实际 DLL 导出并检查 FFmpeg 编译配置：LGPL 2.1+，未启用 GPL 或 nonfree；配置在 `assets/licenses/ffmpeg-build.json`。

绿色版提供 `licenses` 目录与“关于与许可证”，包含许可全文、归属、源码获取与动态库替换说明。配套 `ChronoView-1.0.0-third-party-sources.zip` 提供 Qt/PySide6、FFmpeg 对应版本源码和构建信息。开发测试用的 libx264/libx265 编码工具不进入运行包。

没有制作正式安装包。商业发行前仍需完成目标地区编解码专利及发行条件核对；本次开发验证不构成完整法律审查。

## 架构

```text
app/core/                  只读扫描、文件名日期、混合排序和分类
app/storage/index.py       SQLite 库快照与按变更更新
app/services/              图片读取、有限缩略图队列、异步视频封面
app/ui/main_window.py      照片库状态、年份/月份/媒体逐级导航
app/ui/album_grid.py       年份与月份相册卡片
app/core/albums.py         年/月分组和数量统计
app/ui/photo_grid.py       Model/View 缩略图卡片
app/ui/photo_viewer.py     照片/视频连续查看器
app/ui/video_player.py     内置视频播放控件与资源释放
app/diagnostics.py         显式启用的打包版验证流程
tests/                     第一阶段回归及第二阶段测试
scripts/                   环境、构建、验证、性能和源码准备工具
packaging/                 PyInstaller 绿色版配方和启动说明
assets/licenses/           第三方许可证、归属和实际 FFmpeg 构建配置
```

当前测试结果和已知问题见 `VALIDATION.md`，发布说明见 `docs/releases/V1.0.md`。当前发布标签为 `V1.0`，GitHub 默认分支为 `main`。本地只保留当前发布包，旧测试版与开发备份已清理。

左侧“全部照片”和年份节点：单击整行或小箭头展开/收起；点击行文字同时浏览对应相册。月份节点仍单击进入月份。

侧栏保留“记住照片库位置”选项。取消后立即移除保存的上次目录，后续选择/刷新也不保存它；外观偏好仍记住。取消选目录仍停留隐私页，F5 不会自动打开媒体。命令行 --library 同样在主界面等待主动打开。隐私页用于防止误展示，不提供密码或加密，也不会删除既有本地索引/缩略图缓存。

浏览过程中，点击左侧或右上角的“隐私页”（Ctrl+L）可暂时隐藏媒体、年月/数量和目录路径，仍保留主界面。缩略图列表清空显示并暂停后台封面加载；扫描完成、取消或失败都不会自动退出隐私页。点击继续浏览返回原分类，或明确点击全部照片进入完整列表。查看器内 Ctrl+L 会关闭查看器、停止视频并进入隐私页。启动直接进入主界面隐私页。此功能不提供密码或加密。
