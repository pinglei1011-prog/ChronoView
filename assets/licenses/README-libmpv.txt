ChronoView 1.0.0 — libmpv and linked dependencies

Default video playback: mpv 0.42.0, API 2, Windows x86_64, LGPL build.
Upstream: https://github.com/mpv-player/mpv
Core commit, source checksums, DLL checksum and build provenance are recorded
in libmpv-manifest.json and the matching source/relinking companion.
This is a ChronoView fixed-source build, not an unmodified official DLL.
GPL/nonfree features, Lua/JavaScript, network and disc integrations are disabled.
FFmpeg 7.1.3, libplacebo 7.387.0, FriBidi and libass are built from pinned source.
Other linked archives are supplied as exact relinking inputs with their notices.
Do not confuse the Qt Multimedia FFmpeg configuration with the native player's
configuration: both are recorded separately.

LGPL-2.1.txt, LGPL-3.0.txt and GPL-3.0.txt contain the license texts.
The public mpv client header's ISC notice is retained in libmpv-client.h.
Component notices are in the native subfolder.

The corresponding LGPL sources, build instructions, source hashes and exact
static dependency relinking inputs are supplied in the paired asset:
  ChronoView-1.0.0-third-party-sources.zip
  https://github.com/pinglei1011-prog/ChronoView/releases/tag/V1.0

Libmpv is an independent DLL. Replace
  _internal/vendor/libmpv/libmpv-2.dll
with a compatible build, or set CHRONOVIEW_MPV_LIBRARY to its absolute path
before launching. The application uses API 2 and mpv 0.42 options. This program
places no additional restrictions on modifying/relinking LGPL components, or
reverse engineering needed to debug such modifications. Original media is read-only.

Portions of this software are copyright (C) 2026 The FreeType Project
(https://freetype.org). All rights reserved. Used under the FreeType License.
