#!/usr/bin/env bash
# Functional eval: the whole test suite passes with every network operation denied.
# Uses macOS sandbox-exec; on other systems it reports that it was skipped.
set -euo pipefail
cd "$(dirname "$0")/../.."
if ! command -v sandbox-exec >/dev/null 2>&1; then
  echo "no-network eval: skipped (sandbox-exec is macOS only)"
  exit 0
fi
sandbox-exec -p '(version 1)(allow default)(deny network*)' python3 -m unittest discover -s tests
echo "no-network eval: passed"
