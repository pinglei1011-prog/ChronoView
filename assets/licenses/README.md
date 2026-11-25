# ChronoView 第三方组件与源码

ChronoView 使用 Qt / PySide6 和 FFmpeg 动态库完成照片界面及本地视频解码。
本目录随绿色版一起提供，应用“关于与许可证”中也可查看说明。

| 组件 | 版本 | 许可及源码 |
|---|---|---|
| Qt、PySide6、Shiboken | 6.10.3 | 使用 LGPLv3 允许的动态链接方式；Qt / PySide 保留其原作者权利。https://code.qt.io/cgit/pyside/pyside-setup.git/ ，https://download.qt.io/archive/qt/6.10/6.10.3/ |
| FFmpeg | 7.1.3（Qt 随附构建） | LGPL 2.1 或以后版本及其包含的宽松许可；https://ffmpeg.org/releases/ffmpeg-7.1.3.tar.xz |
| Pillow | 12.3.0 | 随附 Pillow-LICENSE；https://github.com/python-pillow/Pillow/tree/12.3.0 |
| CPython | 3.12.16 | 随附 Python-LICENSE.txt；https://www.python.org/downloads/source/ |

`ffmpeg-build.json` 是从实际分发的 `avcodec-61.dll` 导出的许可与编译配置：动态共享库，未启用 `--enable-gpl` 或 `--enable-nonfree`。运行版不包含开发测试时使用的 imageio-ffmpeg/libx264/libx265 编码工具。

This software uses libraries from the FFmpeg project under the LGPLv2.1 or later.
FFmpeg source is supplied in the companion source archive, together with the recorded build configuration.

LGPL-2.1.txt、LGPL-3.0.txt、GPL-3.0.txt 提供许可全文。Qt/PySide 的商业许可文本是其发行包自带内容，并不表示本项目购买了商业许可。

Qt / FFmpeg DLL 使用原始名称，位于 `_internal/PySide6`，未加密或静态合入应用；用户可以替换兼容的动态库。针对 LGPL 组件的修改、重新链接和为调试这些修改所需的逆向工程不受本应用额外限制。应用不声称拥有这些第三方组件。

Qt Multimedia 归属与第三方组件清单：https://doc.qt.io/qt-6.10/qtmultimedia-index.html#licenses-and-attributions
Qt 其他组件归属：https://doc.qt.io/qt-6.10/licenses-used-in-qt.html
FFmpeg 许可说明：https://ffmpeg.org/legal.html

编码标准的专利权与开源代码许可不同。商业发行前需另行核对目标地区和使用方式的要求；当前开发验证不构成商业发行的完整法律审查。

默认视频播放另外使用 libmpv 的固定源码 LGPL 构建，详情见 README-libmpv.txt 和 libmpv-manifest.json。native 子目录保留静态依赖许可：FreeType 使用 FTL、HarfBuzz 使用其 MIT 风格许可，shaderc/SPIR-V 组件保留 Apache/BSD 等上游许可。GCC 运行库附带 Runtime Library Exception，MinGW/winpthreads 保留其许可；许可文件的存在不表示整个应用采用 GPL。精确链接归档及源码锁位于同版本配套源码/重链接包。
