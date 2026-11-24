# 第一阶段验证记录

日期：2026/11/24（北京时间）

范围：ChronoView 0.1.0 第一阶段 MVP。

## 环境

| 项目 | 实际版本 / 状态 |
|---|---|
| 系统 | Windows 11 x64，10.0.22631 |
| Python | CPython 3.12.16，项目独立 `.venv`，使用现有 uv 管理的解释器 |
| PySide6 / Qt | 6.10.3 |
| Pillow | 12.3.0 |
| pytest | 9.2.0 |
| PyInstaller | 6.22.3 |
| FFmpeg / Inno Setup | 未在 PATH 中发现，本阶段不依赖它们 |
| HEIF 解码器 | 未安装，明确提示可选依赖 |

## 已完成的检查

1. **自动化测试：36 passed。** 最终一次完整回归用时约 6.60 秒。测试仅使用临时目录和合成素材，不使用真实照片。GUI 用 Qt 的 offscreen 后端和 QtTest，实际运行工作线程、模型和窗口交互。
2. **源码原生启动通过。** `main.py --smoke-test --settings-file work\source-final.ini` 正常启动、约两秒关闭，退出码 0。
3. **绿色版构建通过。** 产物位于 `dist\ChronoView\ChronoView.exe`，Qt、Python、Pillow 和图像插件随文件夹提供。
4. **打包版独立启动与浏览基础验证通过。** `scripts\verify_portable.py` 从含中文与空格的其他工作目录启动 EXE，将子进程 PATH 缩减为 Windows System32，移除 PYTHONHOME/PYTHONPATH；EXE 退出码 0。生成临时多层中文目录中的 JPG、PNG 和视频占位文件，验证完成递归扫描、保存所选库路径，并为两张图片实际生成缩略图缓存。没有依赖 PATH 上的 Python。
5. **原生窗口检查。** 使用 computer-use 确认打包版首次启动界面正常、点击“选择文件夹”能打开 Windows 原生目录选择对话框。后续检查遇到 `window is minimized`，恢复时检测到用户输入，停止 UI 自动化。因此不把打包版双击大图、全屏和完整手动浏览记为已实测通过。
6. **视觉检查。** 实际主窗口使用 20 个合成媒体条目进行渲染，检查浅色和深色外观、横竖图比例、视频标识、照片数、视频数、动态年份与未识别分类。截图在 `work\qa-light.png` 和 `work\qa-dark.png`，脚本为 `scripts\visual_check.py`。
7. **启动与安装依赖脚本。** `scripts\setup.ps1` 在已有环境中重跑通过，复用 `.venv`，没有重建或覆盖用户系统 Python。

测试覆盖：IMG/VID 解析、14 位日期真实合法性与闰年、混合稳定排序及两个方向、未知日期位置、年月分类、错误物理目录分类、多级目录、同名不同路径、中文与特殊字符、目录 junction 循环、权限错误、库不可访问、取消扫描前后列表恢复、手动刷新新增/移除文件、EXIF 方向、缓存读取/失效/损坏重建/恢复重试、损坏图片隔离、大图缩放和前后切换、全屏返回、双击只打开一次、Enter 打开、设置恢复。

## 已发现并修复

- 首次损坏图片测试受 Pillow 首次加载解码插件耗时影响，5 秒轮询超时。复查后将异步测试等待上限设为 10 秒；真实工作仍在后台，GUI 不因此阻塞。
- 连接双击和 activated 两个打开信号可能导致关闭查看器后再次打开。改为双击信号与网格内 Enter 快捷键，增加测试确认每次只打开一次。
- 断开后图片错误会留在内存中，刷新成功时清除错误项，允许重新生成缩略图。
- 打包环境 PATH 含其他工具使用的 ICU，PyInstaller 最初收集了带版本化导出符号的第三方 `icuuc.dll`，覆盖 Qt 需要的 Windows 系统 ICU，造成 QtCore 导入错误。已在 spec 过滤错误的 ICU DLL，让 Windows 10/11 使用系统版本；重构建后独立启动和图片解码检查通过。Windows 系统 ICU 的背景见 [Microsoft 文档](https://learn.microsoft.com/en-us/windows/win32/intl/international-components-for-unicode--icu-)。

## 未验证与后续工作

- 未在干净的其他 Windows 10/11 电脑或虚拟机中验证，也未验证不同 DPI、多显示器、4K 屏幕。
- 尚未使用真实 SATA 移动硬盘进行拔插、盘符变化、硬盘休眠或 I/O 超时测试。断开和不可访问场景由临时路径与测试模拟验证。
- 未进行数万张真实照片的吞吐、滚动帧率及内存压力测量。
- HEIC/HEIF、视频封面与内置播放尚未验证；视频播放属于第二阶段。
- 尚无 SQLite 持久化索引和真正增量扫描；退出后的离线媒体列表保存、缓存清理属于第三阶段。
- Inno Setup 配方已提供，**未构建或验证安装包**；正式安装版、签名、干净环境验证属于第四阶段。

以上边界不影响本机已验证的第一阶段核心流程。不得把本记录视为全部四阶段需求已完成。
