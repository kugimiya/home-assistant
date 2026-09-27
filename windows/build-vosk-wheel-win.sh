#!/bin/bash
# Runs inside alphacep/kaldi-win (or jarvis-kaldi-win) Docker image.
# Expects vosk-api checkout mounted at /io (desired tag already checked out).
set -euo pipefail

cd /io/src
echo "Compiling libvosk.dll ..."
EXTRA_LDFLAGS=-Wl,--out-implib,libvosk.lib \
  CXX=x86_64-w64-mingw32-g++-posix \
  EXT=dll \
  KALDI_ROOT=/opt/kaldi/kaldi \
  OPENFST_ROOT=/opt/kaldi/local \
  OPENBLAS_ROOT=/opt/kaldi/local \
  make -j"$(nproc)"

cp /usr/lib/gcc/x86_64-w64-mingw32/*-posix/libstdc++-6.dll /io/src/
cp /usr/lib/gcc/x86_64-w64-mingw32/*-posix/libgcc_s_seh-1.dll /io/src/
cp /usr/x86_64-w64-mingw32/lib/libwinpthread-1.dll /io/src/

export VOSK_SOURCE=/io
export VOSK_SYSTEM=Windows
export VOSK_ARCHITECTURE=64bit

mkdir -p /io/wheelhouse
# Keep Debian 11's pip; upgrading to latest needs Python >=3.10
python3 -m pip install -q wheel setuptools cffi
echo "Packing Python wheel into /io/wheelhouse ..."
python3 -m pip wheel /io/python --no-deps -w /io/wheelhouse

echo "Wheelhouse contents:"
ls -la /io/wheelhouse/
test -n "$(ls /io/wheelhouse/vosk-*.whl 2>/dev/null)" || {
  echo "ERROR: no vosk-*.whl in /io/wheelhouse" >&2
  exit 1
}
