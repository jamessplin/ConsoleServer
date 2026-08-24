#!/bin/sh
set -eu
exec python3 -m pytest -q --backend=live "$@"
