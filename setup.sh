#!/bin/bash

# Get the directory of the current script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Construct the path to the 'install' and 'build' directories
INSTALL_DIR="${SCRIPT_DIR}/install/lib"
BUILD_DIR="${SCRIPT_DIR}/cmake-build-debug/src"

# Initialize an empty variable for new paths
NEW_LD_LIBRARY_PATH=""

# Find all subdirectories in the BUILD_DIR that contain shared libraries (*.so)
if [ -d "$BUILD_DIR" ]; then
  while IFS= read -r dir; do
    # Append the directory if it contains shared libraries
    NEW_LD_LIBRARY_PATH="${NEW_LD_LIBRARY_PATH}:${dir}"
  done < <(find "$BUILD_DIR" -type f -name "*.so" -exec dirname {} \; | sort -u)
fi

# Remove leading colon and append the new paths to LD_LIBRARY_PATH if they are not already present
if [ -n "$NEW_LD_LIBRARY_PATH" ]; then
  export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:+$LD_LIBRARY_PATH:}${NEW_LD_LIBRARY_PATH#:}"
fi

# Print the updated LD_LIBRARY_PATH for verification
echo "Updated LD_LIBRARY_PATH: $LD_LIBRARY_PATH"


## Append 'install' directory to LD_LIBRARY_PATH if it's not already included
#if [[ ":$LD_LIBRARY_PATH:" != *":${INSTALL_DIR}:"* ]]; then
#  export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:+$LD_LIBRARY_PATH:}${INSTALL_DIR}"
#fi
#
## Print the updated LD_LIBRARY_PATH for verification
#echo "Updated LD_LIBRARY_PATH: $LD_LIBRARY_PATH"