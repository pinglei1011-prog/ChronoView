# ChronoView

Windows 本地照片与视频时间线浏览器，Python + PySide6 编写。所有媒体均只读打开，不移动、重命名、删除或编辑原始文件；运行不需要网络、账号或服务器。

当前版本：**0.1.0，第一阶段 MVP**。这是一款可运行的桌面程序，视频播放和正式安装包属于后续阶段。

GitHub 基础版本标签：`v0.1.0`。版本说明及回到基础版本的方法见 `docs/releases/v0.1.0.md`，更新记录见 `CHANGELOG.md`。

## 开始使用

已配置开发环境时，双击项目根目录的 **`run.cmd`**。

若已构建绿色版，双击 **`dist\ChronoView\ChronoView.exe`**。复制到其他电脑时必须复制整个 `ChronoView` 文件夹，包括 `_internal`，不能只复制 EXE。

1. 点击“选择文件夹”，选择照片库最外层目录，可位于内部硬盘或移动硬盘。
2. 软件在后台递归扫描子文件夹，发现的内容会陆续显示。扫描期间可浏览、切换分类或取消扫描。
3. 展开左侧“按年份”查看年份及该年各月份；也可展开“按月份”直接进入月份。数字为该分类照片和视频总数。
4. 用顶部排序框切换新到旧或旧到新；滑块调整缩略图大小。
5. 双击照片或选中后按 Enter 查看大图。左右方向键切换项目；滚轮缩放，鼠标拖动平移；可选择适应窗口、原始尺寸及 F11 全屏。Esc 退出全屏，再次 Esc 关闭查看器。
6. 新增或移除文件后按 F5 或点击“刷新照片库”。程序记住上次成功扫描的路径，启动后自动重新扫描。

移动硬盘未连接时会提示重新连接或重新选择路径。扫描失败或取消会恢复本次会话扫描前的列表；不会因刷新失败而把保存的路径改成错误路径。盘符改变后重新选择文件夹即可。

## 第一阶段已实现

- 无递归深度限制的迭代目录扫描；跳过目录符号链接、Windows junction，避免循环；处理无法访问目录。
- 完整路径区分文件，支持中文、空格和 Unicode 名称。
- 严格识别 `IMG/VID + 14 位数字 + 扩展名`，日期做真实合法性校验；前缀大小写均可。带额外后缀或日期无效的名称归入“未识别日期”。
- 照片、视频按同一个时间序列排列，默认新到旧；日期相同按完整路径稳定排序，未识别日期在两个排序方向下均置于末尾。
- 全部照片、年份、月份、未识别日期分类；只依据文件名，不依据物理目录或文件修改时间。
- JPG/JPEG、PNG、WebP、BMP 照片缩略图及大图；处理 EXIF 方向，保持比例，图片损坏显示占位和错误提示。
- MP4/MOV/AVI/MKV 纳入网格、统计、时间排序和分类，带视频标识。
- Qt Model/View 网格，窗口大小变化自动调整列数；按可见项目申请缩略图，后台线程数及待处理任务数受限，内存缩略图缓存最多 192 张。
- 本地磁盘缩略图缓存，以路径、文件大小和纳秒修改时间生成缓存键；刷新后重试曾经读取失败的图片。
- 深浅主题、缩略图大小调节、照片缩放和平移、全屏、左右键切换、后台大图解码。
- QSettings 保存照片库路径、主题与缩略图大小；关闭时取消扫描、等待后台任务并释放资源。

## 当前边界与后续阶段

**第二阶段：**视频封面、时长与内置播放（播放、暂停、音量、进度、解码失败提示）。本版双击视频会明确显示“第一阶段暂未加入播放”，不会调用外部程序。

**第三阶段：**SQLite 持久化索引、真正的增量扫描、持久化离线库、多万文件场景的测量与优化、磁盘缓存清理。当前刷新会重新枚举目录，但未变化的照片可复用磁盘缩略图缓存；这不等同于已完成增量索引。退出后只保留路径和缩略图，不保存完整媒体列表。缓存暂不自动清理，删除用户缓存目录内的 `thumbnails` 可重建。

**第四阶段：**Inno Setup 安装包构建、干净 Windows 10/11 电脑验证、发布签名和完整依赖审计。已经提供 PyInstaller 绿色版构建脚本及 Inno Setup 配方，配方不代表安装版已验证。

HEIC/HEIF 为可选支持，默认环境不包含解码器。缺少时仍显示文件，打开会提示安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-heif.txt
```

如使用 `uv` 环境且没有 pip：

```powershell
uv pip install --python .venv\Scripts\python.exe -r requirements-heif.txt
```

安装后重新构建，spec 会收集 `pillow_heif` 的数据与二进制依赖。HEIC/HEIF 及其打包解码需要真实素材专项验证，本次第一阶段未验证。

## 新开发电脑配置

建议 Windows 10/11 64 位、Python 3.12。也支持 Python 3.13（尚未专项验证）。

```powershell
Set-Location '你的项目目录'
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup.ps1
.\.venv\Scripts\python.exe main.py
```

脚本优先使用 `uv` 创建项目独立环境，其次使用 `py -3.12` 或已安装的 `python`。首次安装依赖需要网络，应用运行不需要网络。不会安装到系统 Python 环境。

## 测试与构建

```powershell
.\.venv\Scripts\python.exe -m pytest -q
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build.ps1
```

自动化测试仅创建临时目录与测试图片，不接触真实照片。覆盖文件名和非法日期、混合稳定排序、年月分类、多层与同名路径、中文路径、目录链接循环、权限错误、取消、断开保护、手动刷新、EXIF 方向、缩略图缓存与失效、损坏图片、界面扫描与大图交互。

原生窗口启动烟雾测试（使用独立设置，约两秒自动关闭）：

```powershell
.\.venv\Scripts\python.exe main.py --smoke-test --settings-file work\smoke.ini
.\dist\ChronoView\ChronoView.exe --smoke-test --settings-file work\packaged-smoke.ini
```

可用 `--library "照片库路径"` 指定本次启动扫描的目录。`scripts\visual_check.py` 会在项目 `work` 中生成合成测试素材及浅色、深色窗口截图；演示 MP4 只是占位，不是真实视频。

## 架构与安全

```text
main.py                       程序入口、日志、启动选项
app/core/filename_parser.py    文件名时间解析
app/core/library.py            数据结构、排序、分类和计数
app/core/scanner.py            纯 Python 只读扫描逻辑
app/services/images.py         Pillow 解码、EXIF 与可选 HEIF
app/services/thumbnail_service.py 后台缩略图、磁盘缓存和内存上限
app/ui/main_window.py          导航、扫描工作线程、照片库状态
app/ui/photo_grid.py           Qt Model/View 和自绘网格
app/ui/photo_viewer.py         后台大图读取、缩放、导航和全屏
app/ui/theme.py                深色与浅色外观
scripts/                      环境、测试、构建和视觉检查脚本
packaging/                    PyInstaller spec、Inno Setup 配方
tests/                        核心、图片、GUI 自动化测试
```

采用 [Qt QListView 的分批布局](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QListView.html)与自绘 delegate，避免为每个文件创建控件。Pillow 负责图片读取和 EXIF 方向，Qt 工作线程处理扫描与解码，GUI 线程仅更新控件和创建 QPixmap。

本机数据使用 Qt 的用户目录：

- 设置：Windows 当前用户注册表 `HKEY_CURRENT_USER\Software\ChronoView\ChronoView`，也可用 `--settings-file` 隔离。
- 缓存：通常为 `%LOCALAPPDATA%\ChronoView\ChronoView\cache\thumbnails`。
- 日志：通常为 `%LOCALAPPDATA%\ChronoView\ChronoView\chronoview.log`，有大小上限及轮转；仅用于本机排错。

准确位置由 QStandardPaths 根据用户环境决定，代码不硬编码开发机路径。程序只向用户配置、日志和缓存目录写入；原始目录只枚举和读取。扫描异常或图片损坏不会触发任何源文件写入操作。

## 验证记录

本次环境与检查结果见 `VALIDATION.md`。未实际验证的行为不会当成已完成的跨电脑兼容性承诺。
