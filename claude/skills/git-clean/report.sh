#!/usr/bin/env bash
# git-clean report — uruchamia report.py pierwszym działającym Pythonem 3.8+.
# (Na Windowsie `python3` bywa atrapą ze Sklepu, która nic nie robi.)
# Użycie: report.sh [argumenty report.py]

DIR=$(cd "$(dirname "$0")" && pwd)
for py in python3 python py; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1; then
    PYTHONUTF8=1 exec "$py" "$DIR/report.py" "$@"
  fi
done
echo "BŁĄD: brak Pythona 3.8+ — raport HTML niedostępny (audyt i sync działają bez niego)" >&2
exit 3
