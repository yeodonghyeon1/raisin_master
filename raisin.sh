#!/bin/bash
# RAISIN wrapper script for easier command-line usage

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run raisin.py with all arguments passed to this script
python3 "$SCRIPT_DIR/raisin.py" "$@"
