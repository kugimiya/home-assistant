#!/bin/bash
# Runs inside alphacep/kaldi-win (or jarvis-kaldi-win) Docker image.
# Expects vosk-api checkout mounted at /io (desired tag already checked out).
set -euo pipefail
set -x

cd /io/src
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
python3 -m pip install -q --upgrade pip wheel setuptools cffi
python3 -m pip -v wheel /io/python --no-deps -w /io/wheelhouse

ls -la /io/wheelhouse/
