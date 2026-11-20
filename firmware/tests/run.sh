#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
OUTPUT="$(mktemp -t pedal-tests-XXXXXX)"
trap 'rm -f "$OUTPUT"' EXIT

g++ -std=c++17 -Wall -Wextra -Werror -Itests/fake -Iinclude \
  tests/test_journal.cpp src/Journal.cpp -o "$OUTPUT"
"$OUTPUT"

g++ -std=c++17 -Wall -Wextra -Werror -Iinclude \
  tests/test_reed_debounce.cpp -o "$OUTPUT"
"$OUTPUT"
