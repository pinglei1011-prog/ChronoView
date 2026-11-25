#!/usr/bin/env bash
set -euo pipefail
ROOT="$PWD"
PREFIX=/opt/ffbuild
python3 scripts/native/fetch_sources.py
src() { find "$ROOT/native-work/$1" -mindepth 1 -maxdepth 1 -type d | head -n 1; }
export CFLAGS="-O2 -pipe -static-libgcc -I$PREFIX/include"
export CXXFLAGS="-O2 -pipe -static-libgcc -static-libstdc++ -I$PREFIX/include"
export LDFLAGS="-static-libgcc -static-libstdc++ -L$PREFIX/lib"

echo '::group::FFmpeg 7.1.3, built-in codecs and Windows hardware decoding'
pushd "$(src ffmpeg)"
./configure --prefix="$PREFIX" --target-os=mingw32 --arch=x86_64 \
  --enable-cross-compile --cross-prefix="$FFBUILD_CROSS_PREFIX" \
  --cc="$CC" --cxx="$CXX" --ar="${FFBUILD_CROSS_PREFIX}ar" \
  --ranlib="${FFBUILD_CROSS_PREFIX}ranlib" --nm="${FFBUILD_CROSS_PREFIX}nm" \
  --enable-static --disable-shared --disable-autodetect --disable-network \
  --disable-doc --disable-programs --disable-debug --disable-encoders --disable-muxers \
  --disable-avdevice --enable-d3d11va --enable-dxva2 \
  --extra-cflags="$CFLAGS" --extra-cxxflags="$CXXFLAGS" --extra-ldflags="$LDFLAGS"
make -j"$(nproc)"
make install
popd
echo '::endgroup::'

echo '::group::Fixed-source libplacebo, D3D11 only'
PLACEBO="$(src libplacebo)"
meson setup "$PLACEBO/build-cv" "$PLACEBO" --cross-file=/cross.meson \
  --prefix="$PREFIX" --buildtype=release --default-library=static --prefer-static \
  -Dauto_features=disabled -Dd3d11=enabled -Dshaderc=enabled -Dglslang=disabled \
  -Dvulkan=disabled -Dopengl=disabled -Dlcms=disabled -Dxxhash=disabled \
  -Ddemos=false -Dtests=false -Dbench=false -Dfuzz=false
meson compile -C "$PLACEBO/build-cv" -j "$(nproc)"
meson install -C "$PLACEBO/build-cv"
echo '::endgroup::'

echo '::group::Fixed-source FriBidi and libass with native DirectWrite'
FRIBIDI="$(src fribidi)"
meson setup "$FRIBIDI/build-cv" "$FRIBIDI" --cross-file=/cross.meson \
  --prefix="$PREFIX" --buildtype=release --default-library=static \
  -Ddocs=false -Dbin=false -Dtests=false
meson compile -C "$FRIBIDI/build-cv" -j "$(nproc)"
meson install -C "$FRIBIDI/build-cv"
ASS="$(src libass)"
meson setup "$ASS/build-cv" "$ASS" --cross-file=/cross.meson \
  --prefix="$PREFIX" --buildtype=release --default-library=static --prefer-static \
  -Dauto_features=disabled -Ddirectwrite=enabled -Dfontconfig=disabled -Dasm=enabled
meson compile -C "$ASS/build-cv" -j "$(nproc)"
meson install -C "$ASS/build-cv"
echo '::endgroup::'

echo '::group::libmpv 0.42.0, LGPL without unused scripting/network/disc integrations'
MPV="$(src mpv)"
meson setup "$MPV/build-cv" "$MPV" --cross-file=/cross.meson \
  --prefix="$PREFIX" --buildtype=release --default-library=shared --prefer-static \
  -Dauto_features=disabled -Dgpl=false -Dcplayer=false -Dlibmpv=true -Dbuild-date=false \
  -Dlua=disabled -Djavascript=disabled -Dgl=disabled -Dvulkan=disabled \
  -Dd3d11=enabled -Dwasapi=enabled -Dshaderc=enabled -Dspirv-cross=enabled \
  -Dc_link_args="$LDFLAGS -Wl,-Map,$ROOT/native-work/native-link.map" \
  -Dcpp_link_args="$LDFLAGS -Wl,-Map,$ROOT/native-work/native-link.map"
meson compile -C "$MPV/build-cv" -j "$(nproc)"
cp "$MPV/build-cv/libmpv-2.dll" native-output/libmpv-2.dll
"${FFBUILD_CROSS_PREFIX}strip" native-output/libmpv-2.dll
cp "$ROOT/native-work/native-link.map" native-output/metadata/
cp "$MPV/build-cv/meson-info/intro-dependencies.json" native-output/metadata/
cp scripts/native/build.sh scripts/native/fetch_sources.py native-output/metadata/
python3 scripts/native/collect_relink.py
sha256sum native-output/libmpv-2.dll > native-output/SHA256SUMS.txt
echo '::endgroup::'
