import sys
import os

# This script treats the input as a plain text file. It finds a line
# that starts with a specific key and replaces the entire line.
#
# This method preserves all comments, blank lines, and formatting.
#
# Usage: python update_yaml.py <file_path> <key> <value>

def find_and_replace_line(file_path, key, value):
    """Reads a file and replaces the line starting with the given key."""

    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        sys.exit(1)

    # The full new line we want to write.
    # We add a newline character at the end to match file formatting.
    new_line = f'{key}: "{value}"\n'

    # Read all lines from the file into memory
    with open(file_path, 'r') as f:
        lines = f.readlines()

    # Create a new list of lines, replacing the target line if found
    new_content = []
    found_key = False
    # The key must be followed by a colon to be a valid match
    key_to_find = f'{key}:'

    for line in lines:
        # strip() removes leading/trailing whitespace for a robust check
        if line.strip().startswith(key_to_find):
            new_content.append(new_line)
            found_key = True
        else:
            new_content.append(line)

    if not found_key:
        print(f"Warning: Key '{key}' not found in {os.path.basename(file_path)}. File was not changed.")
        return

    # Write the modified content back to the original file
    with open(file_path, 'w') as f:
        f.writelines(new_content)

    print(f"Successfully updated '{key}' in {os.path.basename(file_path)}")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Error: Invalid arguments.")
        print("Usage: python update_yaml.py <file_path> <key> <value>")
        sys.exit(1)

    file_path = sys.argv[1]
    update_key = sys.argv[2]
    update_value = sys.argv[3]

    find_and_replace_line(file_path, update_key, update_value)