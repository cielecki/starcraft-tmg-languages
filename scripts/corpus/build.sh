#!/usr/bin/env bash
# Build CascLib + the CASC string extractors (macOS). See docs/spike-corpus.md.
# One-time. Produces ./casc_list ./casc_grab ./casc_online in this directory.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f CascLib/build/libcasc.a ]; then
  [ -d CascLib ] || git clone --depth 1 https://github.com/ladislav-zezula/CascLib.git
  mkdir -p CascLib/build && cd CascLib/build
  # cmake 4.x dropped <3.5 policy compat -> must pin the minimum or configure fails
  cmake .. -DCMAKE_BUILD_TYPE=Release -DCASC_BUILD_STATIC_LIB=ON \
           -DCMAKE_POLICY_VERSION_MINIMUM=3.5
  cmake --build . -j4
  cd ../..
fi

for t in casc_list casc_grab casc_online; do
  c++ -std=c++11 -O2 -I CascLib/src "$t.cpp" CascLib/build/libcasc.a \
      -lz -framework CoreFoundation -o "$t"
  echo "built $t"
done
echo "Done. Examples:"
echo "  ./casc_list  '/Applications/StarCraft II' gamestrings.txt"
echo "  ./casc_online ./cdncache s2 eu 'mods\\liberty.sc2mod\\plpl.sc2data\\localizeddata\\GameStrings.txt' out"
