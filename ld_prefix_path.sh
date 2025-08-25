SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${SCRIPT_DIR}/install/lib"

# Append 'install' directory to LD_LIBRARY_PATH if it's not already included
if [[ ":$LD_LIBRARY_PATH:" != *":${INSTALL_DIR}:"* ]]; then
  export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:+$LD_LIBRARY_PATH:}${INSTALL_DIR}"
fi

# Print the updated LD_LIBRARY_PATH for verification
echo "Updated LD_LIBRARY_PATH: $LD_LIBRARY_PATH"