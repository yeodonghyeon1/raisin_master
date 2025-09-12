import os
import platform
import re
import shutil
import sys
from collections import defaultdict
import subprocess
from pathlib import Path
import glob
import yaml
import fnmatch
import concurrent.futures
from typing import List, Tuple, Dict, Any, Iterable, Set, Optional
from script.build_tools import find_build_tools

from packaging.version import parse as parse_version, InvalidVersion
import zipfile
from packaging.specifiers import SpecifierSet
import requests
import json

# --- NEW DEPENDENCY ---
# This script now requires the 'packaging' library for version validation.
# Install it via: pip install packaging
try:
    from packaging.requirements import Requirement
    from packaging.version import Version, InvalidVersion
    from packaging.specifiers import InvalidSpecifier
except ImportError:
    print("Error: 'packaging' library not found.")
    print("Please install it running: pip install packaging")
    exit(1)

# Mapping of ROS message types to corresponding C++ types
TYPE_MAPPING = {
    'bool': 'bool',
    'byte': 'uint8_t',
    'char': 'uint8_t',
    'float32': 'float',
    'float64': 'double',
    'int8': 'int8_t',
    'uint8': 'uint8_t',
    'int16': 'int16_t',
    'uint16': 'uint16_t',
    'int32': 'int32_t',
    'uint32': 'uint32_t',
    'int64': 'int64_t',
    'uint64': 'uint64_t',
    'string': 'std::string',
    'wstring': 'std::u16string',
}

class Colors:
    GREEN = '\033[92m'  # Bright Green
    BLUE = '\033[94m'   # Bright Blue
    RED = '\033[91m'    # Bright Red
    RESET = '\033[0m'   # Reset color to default

STRING_TYPES = ['std::string', 'std::u16string']

build_pattern = []

os_type = ""
architecture = ""
os_version = ""
script_directory = ""

# for windows
ninja_path = ""
visual_studio_path = ""
developer_env = dict()
vcpkg_dependencies = set()

always_yes = False

def get_display_width(text):
    """
    Calculates the display width of a string, accounting for specific wide characters.
    """
    # Emojis used in this script that take up 2 character spaces
    wide_chars = {'✅', '⬇️', '⬆️', '🔱', '⚠️'}
    width = 0
    for char in text:
        if char in wide_chars:
            width += 2
        else:
            width += 1
    return width

def is_root():
    """Check if the current user is root."""
    return os.geteuid() == 0

def delete_directory(directory):
    if os.path.exists(directory):
        shutil.rmtree(directory)

def create_service_file(srv_file, project_directory, install_dir):
    """
    Create a service file based on the template, replacing the appropriate placeholders.
    The file is saved in <script_directory>/include/<project_directory>/srv.
    """
    template_path = os.path.join(script_directory, 'templates', 'ServiceTemplate.hpp')

    # Extract the project name from the project directory path
    project_name = os.path.basename(project_directory)

    # Determine the target directory in include/<project_name>/srv
    include_project_srv_dir = os.path.join(script_directory, 'generated', 'include', project_name, 'srv')

    # Recreate the directory to ensure it's clean
    os.makedirs(include_project_srv_dir, exist_ok=True)

    destination_file = os.path.join(install_dir, 'messages', project_name, 'srv', '')
    os.makedirs(destination_file, exist_ok=True)
    shutil.copy2(srv_file, destination_file)

    # Read the template
    with open(template_path, 'r') as template_file:
        template_content = template_file.read()

    # Extract service name from the file
    service_name = os.path.basename(srv_file).replace('.srv', '')

    # Read the service file and split it into request and response parts
    with open(srv_file, 'r') as srv_file_content:
        srv_content = srv_file_content.read()

    with open(srv_file, 'r') as srv_file_content:
        lines = srv_file_content.readlines()

    # Split the content into request and response sections
    if '---' in srv_content:
        request_content, response_content = srv_content.split('---', 1)
    else:
        # If no '---' line is found, it's not a valid service file.
        print(f"Invalid service file format: {srv_file}")
        return

    includes = []

    for line in lines:
        line = line.strip()

        # Ignore comments by splitting at '#' and taking the part before it
        line = line.split('#', 1)[0].strip()

        # Skip empty lines
        if not line or line[0] == '-':
            continue

        parts = line.split()
        if len(parts) == 2:
            data_type, data_name = parts

            # Transform the data type for arrays
            transformed_type, base_type, subproject_path, found_type = transform_data_type(data_type, project_name)

            # Check if the type is a known message type (not a primitive)
            if not found_type and transformed_type != 'Header':
                # Use the preferred include format with relative path
                if not subproject_path:
                    subproject_path = project_name

                snake_str = re.sub(r'(?<!^)(?=[A-Z][a-z]|(?<=[a-z])[A-Z]|(?<=[0-9])(?=[A-Z]))', '_', base_type).lower()
                snake_str = snake_str.replace("__", "_")
                includes.append(f"#include \"../../{subproject_path}/msg/{snake_str}.hpp\"")


    # Process the request and response contents
    request_includes, request_members, request_buffer_members, request_buffer_size = process_service_content(request_content, project_name)
    response_includes, response_members, response_buffer_members, response_buffer_size = process_service_content(response_content, project_name)

    # Replace placeholders in the template
    class_name = service_name.replace('_', '')
    service_content = template_content.replace('@@SERVICE_NAME@@', class_name)
    service_content = service_content.replace('@@INCLUDE_PATH@@', "\n".join(includes))
    service_content = service_content.replace('@@REQUEST_INCLUDES@@', "\n".join(request_includes))
    service_content = service_content.replace('@@REQUEST_MEMBERS@@', "\n  ".join(request_members))

    request_set_buffer_member_string = ""
    request_get_buffer_member_string = ""
    request_equal_buffer_member_string = ""
    response_set_buffer_member_string = ""
    response_get_buffer_member_string = ""
    response_equal_buffer_member_string = ""

    for bm in request_buffer_members:
        request_set_buffer_member_string += f"::raisin::setBuffer(buffer, {bm});\n"
        request_get_buffer_member_string += f"temp = ::raisin::getBuffer(temp, {bm});\n"
        request_equal_buffer_member_string += f"&& this->{bm} == other.{bm} \n"

    for bm in response_buffer_members:
        response_set_buffer_member_string += f"::raisin::setBuffer(buffer, {bm});\n"
        response_get_buffer_member_string += f"temp = ::raisin::getBuffer(temp, {bm});\n"
        response_equal_buffer_member_string += f"&& this->{bm} == other.{bm} \n"

    service_content = service_content.replace('@@REQUEST_SET_BUFFER_MEMBERS@@', request_set_buffer_member_string)
    modified_request_set_buffer_member_string = "\n".join("buffer = " + line for line in request_set_buffer_member_string.splitlines())
    service_content = service_content.replace('@@REQUEST_SET_BUFFER_MEMBERS2@@', modified_request_set_buffer_member_string)
    service_content = service_content.replace('@@REQUEST_GET_BUFFER_MEMBERS@@', request_get_buffer_member_string)
    service_content = service_content.replace('@@REQUEST_EQUAL_BUFFER_MEMBERS@@', request_equal_buffer_member_string)
    service_content = service_content.replace('@@REQUEST_BUFFER_SIZE@@', "\n  ".join(request_buffer_size))

    service_content = service_content.replace('@@RESPONSE_SET_BUFFER_MEMBERS@@', response_set_buffer_member_string)
    modified_response_set_buffer_member_string = "\n".join("buffer = " + line for line in response_set_buffer_member_string.splitlines())
    service_content = service_content.replace('@@RESPONSE_SET_BUFFER_MEMBERS2@@', modified_response_set_buffer_member_string)
    service_content = service_content.replace('@@RESPONSE_GET_BUFFER_MEMBERS@@', response_get_buffer_member_string)
    service_content = service_content.replace('@@RESPONSE_EQUAL_BUFFER_MEMBERS@@', response_equal_buffer_member_string)
    service_content = service_content.replace('@@RESPONSE_BUFFER_SIZE@@', "\n  ".join(response_buffer_size))

    service_content = service_content.replace('@@RESPONSE_INCLUDES@@', "\n".join(response_includes))
    service_content = service_content.replace('@@RESPONSE_MEMBERS@@', "\n  ".join(response_members))

    buffer_member_string = ", ".join(response_buffer_members)
    buffer_member_string = f", {buffer_member_string}" if response_buffer_members else buffer_member_string
    service_content = service_content.replace('@@RESPONSE_BUFFER_MEMBERS@@', buffer_member_string)
    service_content = service_content.replace('@@PROJECT_NAME@@', project_name)

    # Create the service file in the <script_directory>/include/<project_directory>/srv directory
    snake_str = re.sub(r'(?<!^)(?=[A-Z][a-z]|(?<=[a-z])[A-Z]|(?<=[0-9])(?=[A-Z]))', '_', service_name).lower()
    snake_str = snake_str.replace("__", "_")
    output_path = os.path.join(include_project_srv_dir, f'{snake_str}.hpp')

    with open(output_path, 'w') as output_file:
        output_file.write(service_content)

def process_service_content(content, project_name):
    """
    Process the service content (either request or response part).
    It returns the includes, members, and buffer_members lists.
    """
    includes = []
    members = []
    buffer_members = []
    buffer_size = []

    for line in content.splitlines():
        line = line.strip()

        # Ignore comments
        line = line.split('#', 1)[0].strip()

        # Skip empty lines
        if not line:
            continue

        parts = line.split()
        parts_in_two = line.split(' ', 1)

        if len(parts) < 4 and '=' not in parts_in_two[1]:
            initial_value = ''
            if len(parts) == 3:
                data_type, data_name, initial_value = parts
            else:
                data_type, data_name = parts

            # Transform the data type for arrays
            transformed_type, base_type, subproject_path, found_type = transform_data_type(data_type, project_name)
            data_name = re.sub(r'(?<!^)(?=[A-Z][a-z]|(?<=[a-z])[A-Z]|(?<=[0-9])(?=[A-Z]))', '_', data_name).lower()
            data_name = data_name.replace("__", "_")

            # Check if the type is a known message type (not a primitive)
            if not found_type and transformed_type != 'Header':
                # Use the preferred include format with relative path
                includes.append(f"#include \"../../{subproject_path}/msg/{base_type}.hpp\"")

            members.append(f"using _{data_name}_type = {transformed_type};")
            if len(parts) == 3:
                members.append(f"{transformed_type} {data_name} = {initial_value};")
            else:
                members.append(f"{transformed_type} {data_name};")

            buffer_members.append(f"{data_name}")

            if transformed_type.startswith('std::vector') or transformed_type.startswith('std::array'):
                if base_type in STRING_TYPES:
                    buffer_size.append(f"temp += sizeof(uint32_t); \n for (const auto& v : {data_name}) temp += sizeof(uint32_t) + v.size();\n")
                elif base_type in TYPE_MAPPING.values():
                    buffer_size.append(f"temp += {data_name}.size() * sizeof({data_name});\n")
                else:
                    buffer_size.append(f"for (const auto& v : {data_name}) temp += v.getSize();\n")
            else :
                if transformed_type in STRING_TYPES:
                    buffer_size.append(f"temp += sizeof(uint32_t) + {data_name}.size();\n")
                elif transformed_type in TYPE_MAPPING.values() and transformed_type != 'std::string' and transformed_type != 'std::u16string':
                    buffer_size.append(f"temp += sizeof({data_name});\n")
                else:
                    buffer_size.append(f"temp += {data_name}.getSize();\n")

        elif '=' in line:
            parts = line.split(' ', 1)
            members.append(f"static constexpr {TYPE_MAPPING[parts[0]]} {parts[1]};")

    return includes, members, buffer_members, buffer_size

def find_topic_directories(search_directories):
    """
    Search for all subdirectories in <script_directory> containing 'CMakeLists.txt'.
    Return a list of these directories.
    The function will not search further into subdirectories once a 'CMakeLists.txt' file is found.
    :param search_directories: A list of directories to search (e.g., ['src', 'messages']).
    """

    topic_directories = []

    # Walk through the specified directories
    for search_dir in search_directories:
        search_path = os.path.join(script_directory, search_dir)

        for root, dirs, files in os.walk(search_path):
            if 'msg' in dirs or 'srv' in dirs:
                # Add the directory containing CMakeLists.txt to the list
                topic_directories.append(root)
                # Do not recurse into subdirectories (clear the dirs list)
                dirs.clear()

    return topic_directories

def find_project_directories(search_directories, install_dir, packages_to_ignore=None):
    """
    Search for all subdirectories in <script_directory> containing 'CMakeLists.txt'.
    Return a list of these directories.
    The function will not search further into subdirectories once a 'CMakeLists.txt' file is found.

    :param install_dir:
    :param packages_to_ignore:
    :param search_directories: A list of directories to search (e.g., ['src', 'messages']).
    """

    if packages_to_ignore is None:
        packages_to_ignore = []
    project_directories = []

    # Walk through the specified directories
    for search_dir in search_directories:
        search_path = os.path.join(script_directory, search_dir)

        for root, dirs, files in os.walk(search_path):
            project_name = os.path.basename(root)
            if project_name in packages_to_ignore:
                dirs.clear()
                continue
            if 'CMakeLists.txt' in files:
                # Add the directory containing CMakeLists.txt to the list
                project_directories.append(root)
                # Do not recurse into subdirectories (clear the dirs list)
                dirs.clear()

    for project_directory in project_directories:
        # Directories to copy
        directories_to_copy = ['resource', 'config', 'scripts']

        for directory in directories_to_copy:
            # Construct the target directory path
            target_directory = os.path.join(script_directory, install_dir, directory, os.path.basename(project_directory))

            # Ensure the target directory exists, create it if not
            source_dir = os.path.join(project_directory, directory)

            # Check if the source directory exists
            if os.path.exists(source_dir):
                # Define the target path for this directory
                os.makedirs(target_directory, exist_ok=True)
                target_path = os.path.join(target_directory, directory)

                # Copy the entire directory
                shutil.copytree(source_dir, target_path, dirs_exist_ok=True)
        
    return project_directories

def find_interface_files(search_directories, interface_types, packages_to_ignore=None):
    """
    Finds ROS interface files (e.g., .action, .msg, .srv) in specified directories.

    Args:
        script_directory (str): The base path from which to search.
        search_directories (list): A list of subdirectories to search within.
        interface_types (list): A list of interface types to find, e.g., ['action', 'msg', 'srv'].
        packages_to_ignore (list, optional): A list of package names to skip. Defaults to None.

    Returns:
        tuple: A tuple of lists, where each list contains the file paths for an interface
               type, in the same order as specified in `interface_types`.
    """
    if packages_to_ignore is None:
        packages_to_ignore = []

    # This dictionary maps an interface type (e.g., 'action') to its file extension
    # and the list where its found files will be stored.
    interface_map = {interface: (f'.{interface}', []) for interface in interface_types}

    for search_dir in search_directories:
        search_path = Path(script_directory) / search_dir
        generated_dest_dir = Path(script_directory) / 'generated' / 'include'

        if not os.path.isdir(search_path):
            continue

        for root, dirs, files in os.walk(search_path):
            # Prune the search if the package directory should be ignored
            if os.path.basename(root) in packages_to_ignore:
                dirs.clear()
                continue

            if (Path(root) / 'include').is_dir():
                if (Path(root) / 'msg').is_dir() or (Path(root) / 'srv').is_dir():
                    shutil.copytree(Path(root) / 'include',
                                    generated_dest_dir, dirs_exist_ok=True)

            # The name of the directory we are currently in (e.g., 'msg', 'srv')
            current_dir_name = os.path.basename(root)

            # Check if this directory's name matches an interface type we're looking for
            if current_dir_name in interface_map:
                extension, target_list = interface_map[current_dir_name]

                for filename in files:
                    if filename.endswith(extension):
                        full_path = os.path.join(root, filename)
                        target_list.append(full_path)

                # We found an interface directory (e.g., '.../my_package/msg'),
                # so we don't need to search its subdirectories.
                dirs.clear()

    # Extract the populated lists from the map in the correct order
    # and return them as a tuple.
    return tuple(interface_map[interface][1] for interface in interface_types)


def build_dependency_graph(project_directories):
    """
    Build a dependency graph from the list of project directories.
    Each node is a project, and edges represent dependencies (based on find_package).

    The graph is a defaultdict where:
    - key: project_name
    - value: set of dependencies (projects that project_name depends on)

    Parameters:
    - project_directories: List of directories containing the projects.

    Returns:
    - graph: A dictionary where each project has a set of dependencies.
    - in_degree: A dictionary tracking how many dependencies each project has.
    """
    graph = defaultdict(list)

    # Iterate through each project directory
    for project_dir in project_directories:
        # Path to the CMakeLists.txt file for this project
        cmake_file_path = os.path.join(project_dir, 'CMakeLists.txt')

        # Find the project name (assumes the project name is the directory name or can be derived)
        project_name = os.path.basename(project_dir)

        # Get the dependencies of this project
        dependencies = find_dependencies(cmake_file_path)
        graph[project_name] = dependencies

    for key in list(graph.keys()):
        # Keep only elements in the list that are keys of the defaultdict
        graph[key] = [elem for elem in graph[key] if elem in graph]

    return graph


def find_dependencies(cmake_file_path):
    dependencies = []
    try:
        with open(cmake_file_path, 'r') as cmake_file:
            # Read the entire file as a single string to handle multi-line target_link_libraries
            cmake_content = cmake_file.read()

        # Define the regex pattern to match "raisin_find_package(SOMETHING)"
        pattern = r'raisin_find_package\((.*?)\)'

        # List of keywords to ignore (in capital letters)
        ignored_keywords = {'REQUIRED', 'VERSION', 'CONFIG', 'COMPONENTS', 'QUIET', 'EXACT'}

        # Use re.findall() to find all matches for the pattern
        matches = re.findall(pattern, cmake_content)

        # Filter out matches that are keywords in capital letters
        for match in matches:
            if match not in ignored_keywords:
                modified_match = match
                for cmake_keyword in ignored_keywords:
                    modified_match = (modified_match.replace(cmake_keyword, "").strip())

                dependencies.append(modified_match)

        return dependencies

    except FileNotFoundError:
        print(f"Error: The file at {cmake_file_path} was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")

    return dependencies

def move_key_before(dep, keys, key):
    """
    Move `key` right before `before_key` in the list of keys,
    but only if it's not already before `before_key`.
    """

    # Find the index of before_key
    dep_index = keys.index(dep)
    key_index = keys.index(key)

    # Check if the key is already before the before_key
    if key_index > dep_index:
        return keys  # Return the original list without changes

    # Remove the key from its current position
    keys.remove(key)

    # Insert the key right before the given before_key
    keys.insert(dep_index, key)

    return keys


def topological_sort(graph, keys):
    """
    Perform a topological sort on the dependency graph.
    Returns a list of keys sorted in dependency order.
    """

    # Iterate over the keys and check if they appear in the values
    original_keys = keys.copy()

    for i in range(20):
        previous_keys = keys.copy()
        for key in original_keys:
            for dep in graph[key]:  # For each key's dependencies in its value
                if dep in graph:
                    # Move the dependent `dep` before the key in the list, if not already before
                    keys = move_key_before(dep, keys, key)

        if previous_keys == keys:
            return keys

        if i == 19:
            print(f"Cyclic dependency detected")
            sys.exit(1)

    return keys


def update_cmake_file(project_directories, cmake_dir):
    """
    Generate a new CMakeLists.txt file by adding projects that either match
    the global 'build_pattern' (if not empty) or all projects, including their
    full dependency trees.
    """
    # 1. Always build the full dependency graph first to know all relationships
    full_graph = build_dependency_graph(project_directories)
    all_project_names = list(full_graph.keys())

    projects_to_include = set()

    # 2. If build_pattern is set, filter projects. Otherwise, include all.
    if not build_pattern:
        # If build_pattern is empty, include all discovered projects
        projects_to_include = set(all_project_names)
    else:
        # Find initial projects matching the build patterns
        initial_matches = {
            name for name in all_project_names
            for pattern in build_pattern
            if fnmatch.fnmatch(name, pattern)
        }

        # Find all dependencies for the matched projects recursively
        queue = list(initial_matches)
        visited = set()
        while queue:
            project_name = queue.pop(0)
            if project_name in visited:
                continue

            visited.add(project_name)
            projects_to_include.add(project_name)

            # Add its dependencies to the queue to be processed
            dependencies = full_graph.get(project_name, [])
            queue.extend(dependencies)

    # 3. Create a new graph containing only the projects to be included
    filtered_graph = {
        project: [dep for dep in deps if dep in projects_to_include]
        for project, deps in full_graph.items() if project in projects_to_include
    }

    # 4. Perform a topological sort on the filtered set of projects
    sorted_project_names = list(filtered_graph.keys())
    for _ in range(2):  # Assuming this double-sort is for stabilization
        sorted_project_names = topological_sort(filtered_graph, sorted_project_names)

    # 5. Generate the CMakeLists.txt content from the sorted, filtered list
    template_path = os.path.join(script_directory, 'templates', 'CMakeLists.txt')
    with open(template_path, 'r') as template_file:
        cmake_template_content = template_file.read()

    # Create a quick lookup from project name to its full directory path
    project_dir_map = {os.path.basename(d): d for d in project_directories}

    subdirectory_lines = []
    for project_name in sorted_project_names:
        if project_name in project_dir_map:
            project_dir = project_dir_map[project_name]
            if (Path(project_dir) / "CMakeLists.txt").is_file():
                project_dir = project_dir.replace('\\', '/')
                subdirectory_lines.append(f"add_subdirectory({project_dir})")

    cmake_content = cmake_template_content.replace('@@SUB_PROJECT@@', "\n".join(subdirectory_lines))
    cmake_content = cmake_content.replace('@@SCRIPT_DIR@@', script_directory)

    cmake_file_path = os.path.join(script_directory, 'CMakeLists.txt')

    with open(cmake_file_path, 'w') as cmake_file:
        cmake_file.write(cmake_content)

    print(f"📂 Generated CMakeLists.txt at {cmake_file_path} with {len(subdirectory_lines)} projects.")

def transform_data_type(data_type, project_name):
    """
    Transform the data type based on whether it ends in [] or [N].
    """
    found_type = False
    subproject_path = ''

    # Split the data_type by '/' and take the last part
    if '/' in data_type:
        subproject_path, data_type = data_type.rsplit('/', 1)
        if not data_type:
            data_type = subproject_path
            subproject_path = ''

    stripped_data_type = data_type.split('<', 1)[0]
    stripped_data_type = stripped_data_type.split('>', 1)[0]

    # Check for array types (with [] or [N])
    if match := re.match(r'([a-zA-Z0-9_]+)\[(\d+)\]', data_type):
        # Fixed-size array ([N])
        base_type, size = match.groups()
        if base_type in TYPE_MAPPING:
            converted_base_type = TYPE_MAPPING[base_type]
            return f"std::array<{converted_base_type}, {size}>", converted_base_type, subproject_path, base_type in TYPE_MAPPING
        elif not subproject_path:
            return f"std::array<{project_name}::msg::{base_type}, {size}>", base_type, subproject_path, True
        elif subproject_path:
            return f"std::array<{subproject_path}::msg::{base_type}, {size}>", base_type, subproject_path, False
    elif data_type.endswith(']'):
        base_type = data_type.split('[', 1)[0]  # Remove the '[]'
        if base_type in TYPE_MAPPING:
            base_type = TYPE_MAPPING[base_type]
            found_type = True
            return f"std::vector<{base_type}>", base_type, subproject_path, found_type
        elif not subproject_path:
            return f"std::vector<{project_name}::msg::{base_type}>", base_type, subproject_path, False
        elif subproject_path:
            return f"std::vector<{subproject_path}::msg::{base_type}>", base_type, subproject_path, False
    elif stripped_data_type in TYPE_MAPPING:
        return TYPE_MAPPING[stripped_data_type], TYPE_MAPPING[stripped_data_type], subproject_path, True
    elif subproject_path:
        return f"{subproject_path}::msg::{data_type}", data_type, subproject_path, False
    else:
        return f"{project_name}::msg::{data_type}", data_type, subproject_path, False

def create_action_file(action_file, project_directory, install_dir):
    """
    Create a message file based on the template, replacing '@@MESSAGE_NAME@@' with the message file name.
    The file is saved in <script_directory>/include/<project_directory>/msg.
    """
    template_path = os.path.join(script_directory, 'templates', 'ActionTemplate.hpp')

    # Extract the project name from the project directory path
    project_name = os.path.basename(project_directory)

    # Determine the target directory in include/<project_name>/msg
    include_project_msg_dir = os.path.join(script_directory, 'generated', 'include', project_name, 'action')
    destination_file = os.path.join(install_dir, 'messages', project_name, 'action', '')
    os.makedirs(destination_file, exist_ok=True)
    shutil.copy2(action_file, destination_file)

    # Delete the entire include directory before generating new files
    os.makedirs(include_project_msg_dir, exist_ok=True)  # Recreate it

    # Read the template
    with open(template_path, 'r') as template_file:
        template_content = template_file.read()

    # Replace the placeholder with the message file name
    message_name = str(os.path.basename(action_file).replace('.action', ''))
    class_name = message_name.replace('_', '')
    message_content = template_content.replace('@@LOWER_MESSAGE_NAME@@', class_name.lower())
    message_content = message_content.replace('@@MESSAGE_NAME@@', class_name)
    message_content = message_content.replace('@@PROJECT_NAME@@', project_name)

    # Create the message file in the <script_directory>/include/<project_directory>/msg directory
    snake_str = re.sub(r'(?<!^)(?=[A-Z][a-z]|(?<=[a-z])[A-Z]|(?<=[0-9])(?=[A-Z]))', '_', message_name).lower()
    snake_str = snake_str.replace("__", "_")
    output_path = os.path.join(include_project_msg_dir, f'{snake_str}.hpp')

    with open(output_path, 'w') as output_file:
        output_file.write(message_content)

    ### create other interface files
    action_path = Path(action_file)
    # --- 1. Read the action file ---
    try:
        action_file_content = action_path.read_text()
    except FileNotFoundError:
        print(f"❌ ERROR: File not found at '{action_path}'. Please check the path.")
        return
    except Exception as e:
        print(f"❌ ERROR: Could not read file: {e}")
        return

    msg_dir = Path(script_directory) / "temp" / project_name / "msg"
    srv_dir = Path(script_directory) / "temp" / project_name / "srv"
    msg_dir.mkdir(parents=True, exist_ok=True)
    srv_dir.mkdir(parents=True, exist_ok=True)

    # --- 3. Split the action file content ---
    parts = action_file_content.split('---')
    if len(parts) != 3:
        print(f"❌ ERROR: Invalid action file format of {action_file}. Must contain two '---' separators.")
        return

    goal_content, result_content, feedback_content = [part.strip() for part in parts]

    # --- 4. Write each message file ---
    message_definitions = {
        f"{class_name}Goal.msg": goal_content,
        f"{class_name}Result.msg": result_content,
        f"{class_name}Feedback.msg": feedback_content,
    }

    for filename, content in message_definitions.items():
        file_path = msg_dir / filename
        file_path.write_text(content)

    send_goal_content = (f"{class_name}Goal goal\n" +
                         "unique_identifier_msgs/UUID goal_id\n" +
                         "---\n" +
                         "bool accepted\n" +
                         "builtin_interfaces/Time stamp")
    file_path = srv_dir / f"{class_name}SendGoal.srv"
    file_path.write_text(send_goal_content)

    get_result_content = ("unique_identifier_msgs/UUID goal_id\n" +
                          "---\n" +
                          f"{class_name}Result result\n" +
                          "uint8 status")
    file_path = srv_dir / f"{class_name}GetResult.srv"
    file_path.write_text(get_result_content)

    feedback_message_content = (f"{class_name}Feedback feedback\n" +
                                "unique_identifier_msgs/UUID goal_id")
    file_path = msg_dir / f"{class_name}FeedbackMessage.msg"
    file_path.write_text(feedback_message_content)


def create_message_file(msg_file, project_directory, install_dir):
    """
    Create a message file based on the template, replacing '@@MESSAGE_NAME@@' with the message file name.
    The file is saved in <script_directory>/include/<project_directory>/msg.
    """
    template_path = os.path.join(script_directory, 'templates', 'MessageTemplate.hpp')

    # Extract the project name from the project directory path
    project_name = os.path.basename(project_directory)

    # Determine the target directory in include/<project_name>/msg
    include_project_msg_dir = os.path.join(script_directory, 'generated', 'include', project_name, 'msg')
    destination_file = os.path.join(install_dir, 'messages', project_name, 'msg', '')
    os.makedirs(destination_file, exist_ok=True)
    shutil.copy2(msg_file, destination_file)

    # Delete the entire include directory before generating new files
    os.makedirs(include_project_msg_dir, exist_ok=True)  # Recreate it

    # Read the template
    with open(template_path, 'r') as template_file:
        template_content = template_file.read()

    # Replace the placeholder with the message file name
    message_name = os.path.basename(msg_file).replace('.msg', '')
    class_name = message_name.replace('_', '')
    message_content = template_content.replace('@@MESSAGE_NAME@@', class_name)
    message_content = message_content.replace('@@PROJECT_NAME@@', project_name)

    # Read the message file and process its contents
    with open(msg_file, 'r') as msg_file_content:
        lines = msg_file_content.readlines()

    includes = []
    members = []
    buffer_members = []
    buffer_size = []

    for line in lines:
        line = line.strip()

        # Ignore comments by splitting at '#' and taking the part before it
        line = line.split('#', 1)[0].strip()

        # Skip empty lines
        if not line:
            continue

        parts = line.split()
        parts_in_two = line.split(' ', 1)

        if len(parts) < 4  and '=' not in parts_in_two[1]:
            initial_value = ''
            if len(parts) == 3:
                data_type, data_name, initial_value = parts
            else:
                data_type, data_name = parts

            # Transform the data type for arrays
            transformed_type, base_type, subproject_path, found_type = transform_data_type(data_type, project_name)
            data_name = re.sub(r'(?<!^)(?=[A-Z][a-z]|(?<=[a-z])[A-Z]|(?<=[0-9])(?=[A-Z]))', '_', data_name).lower()
            data_name = data_name.replace("__", "_")

            # Check if the type is a known message type (not a primitive)
            if not found_type:
                # Use the preferred include format with relative path
                if not subproject_path:
                    subproject_path = project_name

                if data_type != 'Header':
                    snake_str = re.sub(r'(?<!^)(?=[A-Z][a-z]|(?<=[a-z])[A-Z]|(?<=[0-9])(?=[A-Z]))', '_', base_type).lower()
                    snake_str = snake_str.replace("__", "_")
                    includes.append(f"#include \"../../{subproject_path}/msg/{snake_str}.hpp\"")
                else:
                    includes.append(f"#include \"../../std_msgs/msg/header.hpp\"")

            members.append(f"using _{data_name}_type = {transformed_type};")
            if len(parts) == 3:
                members.append(f"{transformed_type} {data_name} = {initial_value};")
            else:
                members.append(f"{transformed_type} {data_name};")
            buffer_members.append(data_name)

            if transformed_type.startswith('std::vector') or transformed_type.startswith('std::array'):
                if base_type in STRING_TYPES:
                    buffer_size.append(f"temp += sizeof(uint32_t); \n for (const auto& v : {data_name}) temp += sizeof(uint32_t) + v.size();")
                elif base_type in TYPE_MAPPING.values():
                    buffer_size.append(f"temp += {data_name}.size() * sizeof({data_name});")
                else:
                    buffer_size.append(f"for (const auto& v : {data_name}) temp += v.getSize();")
            else :
                if transformed_type in STRING_TYPES:
                    buffer_size.append(f"temp += sizeof(uint32_t) + {data_name}.size();")
                elif transformed_type in TYPE_MAPPING.values() and transformed_type != 'std::string' and transformed_type != 'std::u16string':
                    buffer_size.append(f"temp += sizeof({data_name});")
                else:
                    buffer_size.append(f"temp += {data_name}.getSize();")

        elif '=' in line:
            parts = line.split(' ', 1)
            members.append(f"static constexpr {TYPE_MAPPING[parts[0]]} {parts[1]};")

    # Insert includes and members into the template
    message_content = message_content.replace('@@INCLUDE_PATH@@', "\n".join(includes))
    message_content = message_content.replace('@@MEMBERS@@', "\n  ".join(members))
    message_content = message_content.replace('@@BUFFER_SIZE_EXPRESSION@@', "\n  ".join(buffer_size))

    set_buffer_member_string = ""
    get_buffer_member_string = ""
    equal_buffer_member_string = ""

    for bm in buffer_members:
        set_buffer_member_string += f"::raisin::setBuffer(buffer, {bm});\n"

    for bm in buffer_members:
        get_buffer_member_string += f"temp = ::raisin::getBuffer(temp, {bm});\n"

    for bm in buffer_members:
        equal_buffer_member_string += f"&& this->{bm} == other.{bm} \n"

    message_content = message_content.replace('@@SET_BUFFER_MEMBERS@@', set_buffer_member_string)
    modified_set_buffer_member_string = "\n".join("buffer = " + line for line in set_buffer_member_string.splitlines())
    message_content = message_content.replace('@@SET_BUFFER_MEMBERS2@@', modified_set_buffer_member_string)
    message_content = message_content.replace('@@GET_BUFFER_MEMBERS@@', get_buffer_member_string)
    message_content = message_content.replace('@@EQUAL_BUFFER_MEMBERS@@', equal_buffer_member_string)

    # Create the message file in the <script_directory>/include/<project_directory>/msg directory
    snake_str = re.sub(r'(?<!^)(?=[A-Z][a-z]|(?<=[a-z])[A-Z]|(?<=[0-9])(?=[A-Z]))', '_', message_name).lower()
    snake_str = snake_str.replace("__", "_")
    output_path = os.path.join(include_project_msg_dir, f'{snake_str}.hpp')

    with open(output_path, 'w') as output_file:
        output_file.write(message_content)

    # print(f"Created message file: {output_path}")

def get_ubuntu_version():
    with open('/etc/os-release') as f:
        for line in f:
            if 'VERSION=' in line:
                version = line.split('=')[1].strip().strip('"')
                match = re.search(r'(\d+\.\d+)', version)
                if match:
                    return match.group(1)
    return None

def get_packages_to_ignore():
    """
    Reads a file named 'RAISIN_IGNORE' in the same directory as this script
    and returns a list where each line in the file is an element.
    """
    try:
        # Get the absolute path of the current script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # Construct the full path to 'RAISIN_IGNORE'
        file_path = os.path.join(script_dir, 'RAISIN_IGNORE')

        # Read the file and return its lines as a list
        with open(file_path, 'r') as file:
            lines = [line.strip() for line in file.readlines()]
        return lines

    except FileNotFoundError:
        return []
    except Exception as e:
        raise Exception(f"An error occurred while reading the file: {e}")

def find_git_repos(base_dir):
    """
    Recursively search for directories that contain a .git folder.
    Returns a list of paths that are Git repositories.
    """
    git_repos = []
    for root, dirs, _ in os.walk(base_dir):
        if '.git' in dirs:
            git_repos.append(root)
            # Prevent descending into this repository's subdirectories.
            dirs.clear()
    return git_repos

def install_development_tools():
    """
    Install development tools (clang-format, pre-commit) if not already installed.
    """
    print("Checking and installing development tools...")

    # Check if clang-format is installed
    try:
        subprocess.run(['clang-format', '--version'], capture_output=True, check=True)
        print("✅ clang-format is already installed")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Installing clang-format...")
        try:
            # Install clang-format based on the system
            if platform.system() == "Linux":
                # Try apt first (Ubuntu/Debian)
                try:
                    if is_root():
                        subprocess.run(['apt', 'update'], check=True)
                        subprocess.run(['apt', 'install', '-y', 'clang-format'], check=True)
                    else:
                        subprocess.run(['sudo', 'apt', 'update'], check=True)
                        subprocess.run(['sudo', 'apt', 'install', '-y', 'clang-format'], check=True)
                    print("✅ clang-format installed via apt")
                except subprocess.CalledProcessError:
                    # Try snap as fallback
                    try:
                        if is_root():
                            subprocess.run(['snap', 'install', 'clang-format'], check=True)
                        else:
                            subprocess.run(['sudo', 'snap', 'install', 'clang-format'], check=True)
                        print("✅ clang-format installed via snap")
                    except subprocess.CalledProcessError:
                        print("❌ Failed to install clang-format. Please install manually.")
            else:
                print("❌ Automatic clang-format installation not supported on this platform. Please install manually.")
        except Exception as e:
            print(f"❌ Error installing clang-format: {str(e)}")

        # Check if pre-commit is installed
    pre_commit_installed = False

    # Try system Python first (for git hooks)
    try:
        result = subprocess.run(['/usr/bin/python3', '-m', 'pre_commit', '--version'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            print("✅ pre-commit is already installed (system Python)")
            pre_commit_installed = True
    except Exception:
        pass

    # Try direct command if system Python doesn't work
    if not pre_commit_installed:
        try:
            result = subprocess.run(['pre-commit', '--version'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                print("✅ pre-commit is already installed")
                pre_commit_installed = True
        except Exception:
            pass

    # Try current Python module if direct command failed
    if not pre_commit_installed:
        try:
            result = subprocess.run([sys.executable, '-m', 'pre_commit', '--version'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                print("✅ pre-commit is already installed (python module)")
                pre_commit_installed = True
        except Exception:
            pass

    if not pre_commit_installed:
        print("Installing pre-commit...")
        try:
            # Try to install pre-commit to system Python first (for git hooks)
            # Check if current Python is already system Python3
            commands = ['/usr/bin/python3', '-m', 'pip', 'install', 'pre-commit']
            if not is_root():
                commands.insert(0, 'sudo')
            if sys.executable == '/usr/bin/python3':
                commands.append('--break-system-packages')
            subprocess.run(commands, check=True)
            print("✅ pre-commit installed to system Python via pip")
        except subprocess.CalledProcessError:
            try:
                # Fallback to current Python environment
                subprocess.run([sys.executable, '-m', 'pip', 'install', 'pre-commit'], check=True)
                print("✅ pre-commit installed via pip")
            except subprocess.CalledProcessError:
                try:
                    # Try with pip3 as fallback
                    subprocess.run(['pip3', 'install', 'pre-commit'], check=True)
                    print("✅ pre-commit installed via pip3")
                except subprocess.CalledProcessError:
                    print("❌ Failed to install pre-commit. Please install manually: sudo /usr/bin/python3 -m pip install pre-commit")


def get_commit_hash(repo_path):
    """
    Returns the current commit hash (HEAD) for the repository at repo_path.
    Uses the git command-line tool.
    """
    try:
        commit_hash = subprocess.check_output(
            ['git', '-C', repo_path, 'rev-parse', 'HEAD'],
            stderr=subprocess.STDOUT
        ).decode('utf-8').strip()
        return commit_hash
    except subprocess.CalledProcessError as e:
        print(f"❌ Error getting commit hash for {repo_path}:\n{e.output.decode('utf-8')}")
        return None

def read_existing_data(file_path):
    """
    Reads an existing file and returns a dictionary mapping repository names
    to commit hashes.
    """
    data = {}
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    repo_name = parts[0]
                    commit_hash = parts[1]
                    data[repo_name] = commit_hash
    return data

def write_data(file_path, data):
    """
    Writes the data (a dict of repo names to commit hashes) to the file.
    """
    with open(file_path, 'w') as f:
        for repo, commit in data.items():
            f.write(f"{repo} {commit}\n")

def copy_resource(install_dir):
    target_dir = "resource"
    for root, dirs, files in os.walk(os.path.join(Path.home(), ".raisin")):

        # Check if the directory contains the target architecture subdirectory
        if target_dir in dirs:

            source_dir = os.path.join(root, target_dir)
            dest_dir = os.path.join(script_directory, install_dir, 'resource', os.path.basename(root), target_dir)

            for item in os.listdir(source_dir):
                s = os.path.join(source_dir, item)
                d = os.path.join(dest_dir, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)

def copy_installers(src_dir, install_dir) -> int:
    """
    Scan <script_directory>/src/*/ for install_dependencies.sh files and copy
    each one to <script_directory>/install/<subdir>/install_dependencies.sh.

    Parameters
    ----------
    script_directory : str | pathlib.Path
        The root folder that contains both `src/` and `install/`.

    Returns
    -------
    int
        The number of installer scripts successfully copied.
    """
    script_dir = Path(script_directory).expanduser().resolve()
    dst_root   = script_dir / install_dir
    src_root = Path(script_directory) / src_dir

    copied = 0
    if not src_root.is_dir(): # not building from source
        return
        # raise FileNotFoundError(f"{src_root} does not exist")

    for child in src_root.iterdir():
        if not child.is_dir():
            continue                      # skip non-directories
        src_installer = child / "install_dependencies.sh"
        if not src_installer.is_file():
            continue                      # nothing to copy in this subdir

        dst_subdir = dst_root / "dependencies" / child.name
        dst_subdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_installer, dst_subdir / "install_dependencies.sh")
        copied += 1

    return copied


def deploy_install_packages():
    """
    Finds and copies packages that match the current system's OS and architecture.

    This function scans 'release/install' for packages matching the pattern
    '{target}/{os_type}/{architecture}/{build_type}'. It only considers packages
    where {os_type} and {architecture} match the current system. The contents
    of each valid package are copied into a corresponding directory structure at
    '{script_directory}/install/{target}/{os_type}/{architecture}', merging the
    contents from different build types (e.g., 'release', 'debug').

    Args:
        script_directory (str): The absolute path to the base directory.
    """

    # Create a glob pattern to find all build directories for the current system
    # e.g., .../release/install/*/linux/x86_64/*
    source_pattern = os.path.join(
        script_directory, 'release', 'install', '*', os_type, os_version, architecture, '*'
    )

    # Find all source directories that match
    found_source_dirs = glob.glob(source_pattern)

    if not found_source_dirs:
        print(f"🤷 No installed packages found for the current system ({os_type}/{os_version}/{architecture}).")
        return

    print(f"🚀 Deploying installed packages for system: {os_type}/{os_version}/{architecture}")
    deployed_targets = set()

    try:
        for source_dir in found_source_dirs:
            if not os.path.isdir(source_dir):
                continue

            if os.path.isdir(Path(script_directory) / 'src' / Path(source_dir).parts[-5]):
                continue

            # Use pathlib to easily get the 'target' name from the path
            # The path is .../install/{target}/{os}/{os_version}/{arch}/{build_type}
            p = Path(source_dir)
            target_name = p.parents[3].name
            final_dest_dir = os.path.join(script_directory, 'install')
            generated_dest_dir = os.path.join(script_directory, 'generated')

            # Print the target-specific message only once
            if target_name not in deployed_targets:
                print(f"  -> Deploying target '{target_name}' to: {final_dest_dir}")
                deployed_targets.add(target_name)

            release_yaml_path = p / 'release.yaml'
            if release_yaml_path.is_file():
                try:
                    with open(release_yaml_path, 'r') as f:
                        release_data = yaml.safe_load(f)
                        # Ensure data was loaded and is a dictionary
                        if release_data and isinstance(release_data, dict):
                            # Safely get the list of dependencies, default to empty list
                            dependencies = release_data.get('vcpkg_dependencies', [])
                            if dependencies and isinstance(dependencies, list):
                                # Use set.update() to add all items from the list
                                vcpkg_dependencies.update(dependencies)
                except yaml.YAMLError as ye:
                    print(f"    - ⚠️ Warning: Could not parse {release_yaml_path}: {ye}")
                except IOError as ioe:
                    print(f"    - ⚠️ Warning: Could not read {release_yaml_path}: {ioe}")


            # Copy contents, merging files from different build_types
            shutil.copytree(source_dir, final_dest_dir, dirs_exist_ok=True)

            if (p / 'generated').is_dir():
                shutil.copytree(p / 'generated', generated_dest_dir, dirs_exist_ok=True)

            if (p / 'install_dependencies.sh').is_file():
                os.makedirs(Path(script_directory) / 'install/dependencies' / target_name, exist_ok=True)
                shutil.copy(p / 'install_dependencies.sh',
                            Path(script_directory) / 'install/dependencies' / target_name / 'install_dependencies.sh')

        if deployed_targets:
            print(f"\n✅ Successfully deployed {deployed_targets} target(s).")

    except Exception as e:
        print(f"❌ An error occurred during deployment: {e}")

def collect_src_vcpkg_dependencies():
    """
    Scans subdirectories in '{script_directory}/src' for 'release.yaml' files.

    For each 'release.yaml' found, it reads the file and checks for a
    'vcpkg_dependencies' node. If the node exists, its contents (a list of
    strings) are merged into a master set to collect all unique dependencies.

    Returns:
        set: A set containing all unique vcpkg dependency strings found.
    """
    src_path = Path(script_directory) / 'src'
    if not src_path.is_dir():
        print(f"🤷 Source directory not found at: {src_path}")
        return

    print(f"🔍 Scanning for vcpkg dependencies in: {src_path}")

    # Iterate over each item in the 'src' directory
    for project_dir in src_path.iterdir():
        # Process only if the item is a directory
        if not project_dir.is_dir():
            continue

        release_yaml_path = project_dir / 'release.yaml'

        # Check if 'release.yaml' exists in the subdirectory
        if release_yaml_path.is_file():
            try:
                with open(release_yaml_path, 'r') as f:
                    release_data = yaml.safe_load(f)

                    # Ensure data was loaded and is a dictionary
                    if release_data and isinstance(release_data, dict):
                        # Safely get the list of dependencies, defaulting to an empty list
                        dependencies = release_data.get('vcpkg_dependencies', [])

                        if dependencies and isinstance(dependencies, list):
                            print(f"  -> Found {len(dependencies)} dependencies in '{project_dir.name}'")
                            # Merge the found dependencies into the main set
                            vcpkg_dependencies.update(dependencies)

            except yaml.YAMLError as e:
                print(f"  -> ⚠️ Error parsing YAML in '{project_dir.name}': {e}")
            except IOError as e:
                print(f"  -> ⚠️ Error reading file in '{project_dir.name}': {e}")

    return

def generate_vcpkg_json():
    """
    Reads a vcpkg.json template, replaces a placeholder with dependencies,
    and saves the new file.

    Args:
        script_directory (str): The absolute path to the script's directory.
        vcpkg_dependencies (set): A set of strings representing vcpkg package names.
    """
    # Define the template and output file paths
    script_path = Path(script_directory)
    template_path = script_path / "templates" / "vcpkg.json"
    output_path = script_path / "vcpkg.json"

    # --- 1. Format the dependencies ---
    # Convert the set of dependencies into a single, comma-separated string
    # where each item is enclosed in double quotes.
    # e.g., {'fmt', 'spdlog'} -> '"fmt", "spdlog"'
    deps_string = ", ".join(f'"{dep}"' for dep in sorted(list(vcpkg_dependencies)))

    try:
        # --- 2. Read the template file ---
        print(f"Reading template from: {template_path}")
        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()

        # --- 3. Replace the placeholder ---
        new_content = template_content.replace("@@DEP@@", deps_string)

        # --- 4. Write to the output file ---
        # Using "w" mode will create the file or overwrite it if it already exists.
        print(f"Writing new vcpkg.json to: {output_path}")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        print("✅ Successfully generated vcpkg.json.")

    except FileNotFoundError:
        print(f"❌ Error: Template file not found at {template_path}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

def setup(package_name = "", build_type = "", build_dir = ""):
    """
    setup function to find project directories, msg, and srv files and generate message and service files.
    """

    if package_name == "":
        src_dir = 'src'
        install_dir = 'install'
    else:
        src_dir = 'src/' + package_name
        install_dir = f'release/install/{package_name}/{os_type}/{os_version}/{architecture}/{build_type}'

    delete_directory(os.path.join(script_directory, 'generated'))  # Delete the whole 'include' directory
    delete_directory(Path(script_directory) / install_dir)
    os.makedirs(Path(script_directory) / install_dir, exist_ok=True)

    if build_dir:
        os.makedirs(build_dir, exist_ok=True)

    packages_to_ignore = get_packages_to_ignore()

    action_files = find_interface_files([src_dir], ['action'], packages_to_ignore)[0]

    project_directories = find_project_directories([src_dir], install_dir, packages_to_ignore)

    # Handle .action files
    for action_file in action_files:
        create_action_file(action_file, Path(action_file).parent.parent, install_dir)

    msg_files, srv_files = find_interface_files([src_dir, 'temp'], ['msg', 'srv'], packages_to_ignore)

    # Handle .msg files
    for msg_file in msg_files:
        create_message_file(msg_file, Path(msg_file).parent.parent, install_dir)

    # Handle .srv files
    for srv_file in srv_files:
        create_service_file(srv_file, Path(srv_file).parent.parent, install_dir)

    # Update the CMakeLists.txt based on the template
    update_cmake_file(project_directories, build_dir)

    copy_installers(src_dir, install_dir)

    if package_name == "": # this means we are not in the release mode
        copy_resource(install_dir)

    os.makedirs(os.path.join(script_directory, 'generated/include'), exist_ok=True)
    shutil.copy(os.path.join(script_directory, 'templates', 'raisin_serialization_base.hpp'),
                os.path.join(script_directory, 'generated/include'))

    # create release tag
    install_release_file = Path(script_directory) / 'install' / "release.txt"

    # Read existing data if the file already exists.
    existing_data = read_existing_data(install_release_file)
    output_file = Path(script_directory) / install_dir / "release.txt"

    # Find Git repositories under the base directory.
    git_repos = find_git_repos(script_directory + "/src")
    git_repos.append(script_directory)
    new_data = {}

    if not git_repos:
        print("No Git repositories found.")
    else:
        for repo in git_repos:
            commit_hash = get_commit_hash(repo)
            if commit_hash:
                # Use just the folder name for the repository.
                repo_name = os.path.basename(repo)
                new_data[repo_name] = commit_hash
                print(f"✅ Found {repo_name}: {commit_hash}")

    # Merge: New data overwrites any duplicate repository names in existing data.
    merged_data = existing_data.copy()
    merged_data.update(new_data)

    # Write the merged result to the output file.
    write_data(output_file, merged_data)
    print(f"💾 Wrote git hash file: {output_file}")

    # copy raisin serialization base
    src_file = os.path.join(script_directory, "templates", "raisin_serialization_base.hpp")
    dest_dir = os.path.join(script_directory, "generated", "include")

    os.makedirs(dest_dir, exist_ok=True)  # Ensure destination directory exists
    shutil.copy2(src_file, dest_dir)

    os.makedirs(Path(script_directory) / 'install', exist_ok=True)

    # install generated files
    shutil.copytree(Path(script_directory) / "generated",
                    Path(script_directory) / install_dir / 'generated', dirs_exist_ok=True)

    deploy_install_packages()

    shutil.copy2(Path(script_directory) / 'templates/install_dependencies.sh',
                 Path(script_directory) / 'install/install_dependencies.sh')

    collect_src_vcpkg_dependencies()
    generate_vcpkg_json()

def release(target, build_type):
    """
    Builds the project, creates a release archive, and uploads it to GitHub,
    prompting for overwrite if the asset already exists.
    """
    # --- This initial part of the function remains the same ---
    target_dir = os.path.join(script_directory, 'src', target)
    install_dir = f"{script_directory}/release/install/{target}/{os_type}/{os_version}/{architecture}/{build_type}"

    if not os.path.isdir(target_dir):
        print(f"❌ Error: Target '{target}' not found in '{os.path.join(script_directory, 'src')}'.")
        return

    release_file_path = os.path.join(target_dir, 'release.yaml')
    repository_file_path = os.path.join(script_directory, 'repositories.yaml')

    if not os.path.isfile(release_file_path):
        print(f"❌ Error: 'release.yaml' not found in '{target_dir}'.")
        return

    print(f"✅ Found release file for '{target}'.")

    try:
        with open(release_file_path, 'r') as file:
            with open(repository_file_path, 'r') as repository_file:
                details = yaml.safe_load(file)
                repositories = yaml.safe_load(repository_file)

                print(f"\n--- Setting up build for '{target}' ---")
                build_dir = Path(script_directory) / "release" / "build" / target
                setup(package_name = target, build_type=build_type, build_dir = str(build_dir)) # Assuming setup is defined
                os.makedirs(build_dir / "build", exist_ok=True)

                print("⚙️  Running CMake...")

                if platform.system().lower() == "linux":
                    cmake_command = ["cmake",
                                     "-S", script_directory,
                                     "-G", "Ninja",
                                     "-B", build_dir / "build",
                                     f"-DCMAKE_INSTALL_PREFIX={install_dir}",
                                     f"-DCMAKE_BUILD_TYPE={build_type}",
                                     "-DRAISIN_RELEASE_BUILD=ON"]
                    subprocess.run(cmake_command, check=True, text=True)
                    print("✅ CMake configuration successful.")
                    print("🛠️  Building with Ninja...")
                    core_count = int(os.cpu_count() / 2) or 4
                    print(f"🔩 Using {core_count} cores for the build.")
                    build_command = ["ninja", "install", f"-j{core_count}"]

                    subprocess.run(build_command, cwd=build_dir / "build", check=True, text=True)
                else:
                    cmake_command = ["cmake",
                                     "--preset", build_type.lower(),
                                     "-S", script_directory,
                                     "-B", build_dir / "build",
                                     f"-DCMAKE_TOOLCHAIN_FILE={script_directory}/vcpkg/scripts/buildsystems/vcpkg.cmake",
                                     f"-DCMAKE_INSTALL_PREFIX={install_dir}",
                                     "-DRAISIN_RELEASE_BUILD=ON",
                                     *( [f"-DCMAKE_MAKE_PROGRAM={ninja_path}"] if ninja_path else [] ),]
                    subprocess.run(cmake_command, check=True, text=True, env=developer_env)
                    print("✅ CMake configuration successful.")
                    print("🛠️  Building with Ninja...")

                    subprocess.run(
                        ["cmake", "--build", str(build_dir / "build"), "--parallel"],
                        check=True, text=True, env=developer_env
                    )

                    subprocess.run(
                        ["cmake", "--install", str(build_dir / "build")],
                        check=True, text=True, env=developer_env
                    )

                print(f"✅ Build for '{target}' complete!")

                shutil.copy(Path(script_directory) / 'src' / target / 'release.yaml', Path(install_dir) / 'release.yaml')
                if (Path(script_directory) / 'src' / target / 'install_dependencies.sh').is_file():
                    shutil.copy(Path(script_directory) / 'src' / target / 'install_dependencies.sh', Path(install_dir) / 'install_dependencies.sh')

                print("\n--- Creating Release Archive ---")
                version = details.get('version', '0.0.0')
                archive_name_base = f"{target}-{os_type}-{os_version}-{architecture}-{build_type}-v{version}"
                release_dir = Path(script_directory) / 'release'
                archive_file = release_dir / archive_name_base
                print(f"📦 Compressing '{install_dir}'...")
                shutil.make_archive(
                    base_name=str(archive_file),
                    format='zip',
                    root_dir=str(install_dir)
                )
                print(f"✅ Successfully created archive: {archive_file}.zip")

                secrets_path = os.path.join(script_directory, 'secrets.yaml')
                if not os.path.isfile(secrets_path):
                    print("❌ Error: 'secrets.yaml' not found. Cannot upload to GitHub.")
                    return
                with open(secrets_path, 'r') as secrets_file:
                    secrets = yaml.safe_load(secrets_file)

                print("\n--- Uploading to GitHub Release ---")

                release_info = repositories.get(target)
                if not (release_info and release_info.get('url')):
                    print(f"ℹ️ Repository URL for '{target}' not found in 'repositories.yaml'. Skipping GitHub release.")
                    return

                repo_url = release_info['url']
                match = re.search(r'git@github\.com:(.*)\.git', repo_url)
                repo_slug = match.group(1) if match else None
                if not repo_slug:
                    print(f"❌ Error: Could not parse repository from URL: {repo_url}")
                    return

                owner = repo_slug.split('/')[0]
                token = secrets.get("gh_tokens", {}).get(owner)
                if not token:
                    print(f"❌ Error: Token for owner '{owner}' not found in secrets.yaml.")
                    return

                auth_env = os.environ.copy()
                auth_env["GH_TOKEN"] = token
                tag_name = f"v{version}"

                archive_filename = os.path.basename(archive_file) + ".zip"
                archive_file_str = str(archive_file) + ".zip"

                # 1. Check if the release and asset already exist
                release_exists = True
                asset_exists = False
                try:
                    print(f"Checking status of release '{tag_name}' in '{repo_slug}'...")
                    list_cmd = ["gh", "release", "view", tag_name, "--repo", repo_slug, "--json", "assets"]
                    result = subprocess.run(list_cmd, check=True, capture_output=True, text=True, env=auth_env)
                    release_data = json.loads(result.stdout)
                    existing_assets = [asset['name'] for asset in release_data.get('assets', [])]
                    if archive_filename in existing_assets:
                        asset_exists = True

                except subprocess.CalledProcessError as e:
                    if "release not found" in e.stderr:
                        release_exists = False
                    else:
                        print(f"❌ Error checking release status: {e.stderr}")
                        return

                # 2. Decide whether to create, upload, or prompt for overwrite
                if not release_exists:
                    print(f"✅ Release '{tag_name}' does not exist. Creating a new one...")
                    gh_create_cmd = [
                        "gh", "release", "create", tag_name, archive_file_str,
                        "--repo", repo_slug, "--title", f"Release {tag_name}",
                        "--notes", f"Automated release of version {version}."
                    ]
                    subprocess.run(gh_create_cmd, check=True, capture_output=True, text=True, env=auth_env)
                    print(f"✅ Successfully created new release and uploaded '{archive_filename}'.")
                elif asset_exists:
                    if not always_yes:
                        prompt = input(f"⚠️ Asset '{archive_filename}' already exists. Overwrite? (y/n): ").lower()
                    else:
                        prompt = 'y'

                    if always_yes or prompt in ['y', 'yes']:
                        print(f"🚀 Overwriting asset...")
                        gh_upload_cmd = [
                            "gh", "release", "upload", tag_name, archive_file_str,
                            "--repo", repo_slug, "--clobber"
                        ]
                        subprocess.run(gh_upload_cmd, check=True, capture_output=True, text=True, env=auth_env)
                        print(f"✅ Successfully overwrote asset in release '{tag_name}'.")
                    else:
                        print(f"🚫 Upload for '{archive_filename}' cancelled by user.")
                else: # Release exists, but asset does not
                    print(f"🚀 Uploading new asset to existing release '{tag_name}'...")
                    gh_upload_cmd = [
                        "gh", "release", "upload", tag_name, archive_file_str,
                        "--repo", repo_slug
                    ]
                    subprocess.run(gh_upload_cmd, check=True, capture_output=True, text=True, env=auth_env)
                    print(f"✅ Successfully uploaded asset to release '{tag_name}'.")

    # Keep your existing exception handling
    except FileNotFoundError as e:
        print(f"❌ Command not found: '{e.filename}'. Is the required tool (cmake, ninja, zip, gh) installed and in your PATH?")
    except subprocess.CalledProcessError as e:
        print(f"❌ A command failed with exit code {e.returncode}:\n{e.stderr}")
    except yaml.YAMLError as e:
        print(f"🔥 Error parsing YAML file: {e}")
    except Exception as e:
        print(f"🔥 An unexpected error occurred: {e}")

def install(targets, build_type):
    """
    Downloads and installs packages and their dependencies recursively. It automatically
    processes all packages in the 'src' directory, then prioritizes existing precompiled
    versions, then local sources, before downloading from GitHub.

    Args:
        script_directory (str): The root directory where config files are located
                                and where packages will be installed.
        targets (list): A list of strings, each specifying a package to install,
                        e.g., ["raisin", "my-plugin>=1.2<2.0"].
                        :param build_type:
    """
    print("🚀 Starting recursive installation process...")
    script_dir_path = Path(script_directory)

    # ## 1. Load Configurations (Omitted for brevity)
    all_repositories = {}
    repo_files = sorted(list(set(glob.glob(str(script_dir_path / '*_repositories.yaml')) + glob.glob(str(script_dir_path / 'repositories.yaml')))))
    for file_path in repo_files:
        with open(file_path, 'r') as f:
            repo_data = yaml.safe_load(f)
            if repo_data:
                all_repositories.update(repo_data)
    secrets_path = script_dir_path / 'secrets.yaml'
    try:
        with open(secrets_path, 'r') as f:
            secrets = yaml.safe_load(f)
            tokens = secrets.get('gh_tokens', {})
    except FileNotFoundError:
        print(f"❌ Error: Secrets file not found at {secrets_path}")
        return

    # ## 3. Process Installation Queue
    install_queue = list(targets)

    src_dir = script_dir_path / 'src'
    if src_dir.is_dir():
        print(f"🔍 Scanning for local source packages in '{src_dir}'...")
        local_src_packages = [path.name for path in src_dir.iterdir() if path.is_dir()]
        if local_src_packages:
            print(f"  -> Found local packages to process: {local_src_packages}")
            install_queue.extend(local_src_packages)

    processed_packages = set()
    session = requests.Session()
    is_successful = True

    while install_queue:
        target_spec = install_queue.pop(0)

        match = re.match(r'^\s*([a-zA-Z0-9_.-]+)\s*(.*)\s*$', target_spec)
        if not match:
            print(f"⚠️ Warning: Could not parse target specifier '{target_spec}'. Skipping.")
            continue

        package_name, spec_str = match.groups()
        spec_str = spec_str.strip()

        try:
            if not spec_str:
                spec = SpecifierSet(">=0.0.0")
            else:
                specifiers_list = re.findall(r'[<>=!~]+[\d.]+', spec_str)
                formatted_spec_str = ', '.join(specifiers_list)
                formatted_spec_str = formatted_spec_str.replace(">, =", ">=")
                spec = SpecifierSet(formatted_spec_str)
        except Exception as e:
            print(f"❌ Error: Invalid version specifier '{spec_str}' for package '{package_name}'. Skipping. Error: {e}")
            is_successful = False
            continue

        def check_local_package(path, package_type):
            """Helper to check a local/precompiled package, its version, and dependencies."""
            if not path.is_dir():
                return False
            is_valid = False
            dependencies = []
            release_yaml_path = path / 'release.yaml'
            if not release_yaml_path.is_file():
                if not spec_str:
                    is_valid = True
            else:
                with open(release_yaml_path, 'r') as f:
                    release_info = yaml.safe_load(f) or {}
                    version_str = release_info.get('version')
                    dependencies = release_info.get('dependencies', [])
                    if not version_str:
                        if not spec_str:
                            is_valid = True
                    else:
                        try:
                            version_obj = parse_version(version_str)
                            if spec.contains(version_obj):
                                is_valid = True
                        except InvalidVersion:
                            print(f"⚠️ Invalid version '{version_str}' in {package_type} release.yaml. Ignoring.")
            if is_valid:
                # print(f"✅ Found valid local match for '{package_name}' satisfying '{spec}' in {package_type}")
                if dependencies:
                    install_queue.extend(dependencies)
                return True
            return False

        # ... (rest of the installation logic remains unchanged) ...
        # Priority 1: Check precompiled
        precompiled_path = (script_dir_path / 'release/install' / package_name / os_type / os_version
                            / architecture / build_type)
        if check_local_package(precompiled_path, "release/install"):
            continue

        # Priority 2: Check local source
        local_src_path = script_dir_path / 'src' / package_name
        if check_local_package(local_src_path, "local source"):
            continue
        if local_src_path.is_dir():
            print(f"❌ Error: Different version of '{package_name}' exists in local source")
            continue

        # Priority 3: Find and install remote release
        repo_info = all_repositories.get(package_name)
        if not repo_info or 'url' not in repo_info:
            print(f"⚠️ Warning: No repository URL found for '{package_name}'. Skipping.")
            continue

        git_url = repo_info['url']
        match = re.search(r'git@github.com:(.*)/(.*)\.git', git_url)
        if not match:
            print(f"❌ Error: Could not parse GitHub owner/repo from URL '{git_url}'.")
            is_successful = False
            continue

        owner, repo_name = match.groups()
        token = tokens.get(owner)
        if token:
            session.headers.update({'Authorization': f'token {token}', 'Accept': 'application/vnd.github.v3+json'})
        else: # Clear auth header if no token for this owner
            if 'Authorization' in session.headers:
                del session.headers['Authorization']

        try:
            api_url = f"https://api.github.com/repos/{owner}/{repo_name}/releases"
            response = session.get(api_url)
            response.raise_for_status()
            releases_list = response.json()

            best_release = None
            best_version = parse_version("0.0.0")

            for release in releases_list:
                tag = release.get('tag_name')
                if not tag or release.get('prerelease'):
                    continue
                try:
                    current_version = parse_version(tag)
                    if spec.contains(current_version) and current_version >= best_version:
                        best_version = current_version
                        best_release = release
                except InvalidVersion:
                    continue

            if not best_release:
                print(f"❌ Error: No release found for '{package_name}' that satisfies spec '{spec}'.")
                is_successful = False
                continue

            release_data = best_release
            version = release_data['tag_name']

            if (package_name, version) in processed_packages:
                continue
            processed_packages.add((package_name, version))

            asset_name = f"{package_name}-{os_type}-{os_version}-{architecture}-{build_type}-{version}.zip"
            asset_api_url = next((asset['url'] for asset in release_data.get('assets', []) if asset['name'] == asset_name), None)

            if not asset_api_url:
                print(f"❌ Error: Could not find asset '{asset_name}' for release '{version}'.")
                is_successful = False
                continue

            install_dir = script_dir_path / 'release/install' / package_name / os_type / os_version / architecture / build_type
            download_path = Path(script_directory) / 'install' / asset_name
            download_path.parent.mkdir(parents=True, exist_ok=True)
            if install_dir.exists():
                shutil.rmtree(install_dir)
            install_dir.mkdir(parents=True, exist_ok=True)

            print("-" * 40)
            print(f"⬇️  Downloading {asset_name}...")
            download_headers = {'Accept': 'application/octet-stream'}
            if token:
                download_headers['Authorization'] = f'token {token}'

            with session.get(asset_api_url, headers=download_headers, stream=True) as r:
                r.raise_for_status()
                with open(download_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

            print(f"📂 Unzipping to {install_dir}...")
            with zipfile.ZipFile(download_path, 'r') as zip_ref:
                zip_ref.extractall(install_dir)
            download_path.unlink()
            print(f"✅ Successfully installed '{package_name}=={version}'.")
            print("-" * 40)

            release_yaml_path = install_dir / 'release.yaml'
            if release_yaml_path.is_file():
                with open(release_yaml_path, 'r') as f:
                    release_info = yaml.safe_load(f)
                    dependencies = release_info.get('dependencies', [])
                    if dependencies:
                        install_queue.extend(dependencies)

        except Exception as e:
            print(f"❌ An error occurred while processing '{package_name}': {e}")
            is_successful = False

    if is_successful:
        print("🎉🎉🎉 Installation process finished successfully.")
    else:
        print("❌ Installation process finished with errors.")


def print_help():
    """Displays the comprehensive help message for the script."""
    script_name = os.path.basename(sys.argv[0])
    print(f"RAISIN Build & Management Tool 🍇")
    print("="*60)
    print(f"Usage: python {script_name} <command> [options]\n")
    print("Global Options:")
    print("  --yes")
    print("    Answers 'yes' to all prompts, such as overwriting release assets.")
    print("\n## Core Commands")
    print("-" * 60)
    print("  setup [target ...]")
    print("    🛠️  Generates message headers and configures the main CMakeLists.txt")
    print("        for a local development build. If [target...] is provided (e.g., 'core', 'gui'),")
    print("        it configures only those targets and their dependencies (using RAISIN_BUILD_TARGETS.yaml).")
    print("        If no targets are given, it configures all projects found in 'src/'.")
    print("-" * 60)
    print("  build <debug|release> [install]")
    print("    ⚙️  Runs the 'setup' step, then compiles the project using Ninja.")
    print("        The build type ('debug' or 'release') must be specified.")
    print("        Optionally add 'install' to install artifacts to the 'install/' directory.")
    print("-" * 60)
    print("  release <target ...> [debug|release]")
    print("    📦 Creates, archives, and uploads a distributable package for one or more")
    print("        targets. Packages are built and placed in 'release/install/'")
    print("        and the final ZIP is uploaded to the corresponding GitHub Release.")
    print("        - Build type defaults to 'release' if not specified.")
    print("-" * 60)
    print("  install [package_spec ...] [debug|release]")
    print("    🚀 Downloads and installs pre-compiled packages and their dependencies.")
    print("        - If no packages are listed, it processes/installs all local 'src/' packages.")
    print("        - A 'package_spec' supports version constraints (e.g., 'raisin_core>=1.2.3').")
    print("        - Build type defaults to 'release' if not specified.")
    print("\n## Utility Commands")
    print("-" * 60)
    print("  index local")
    print("    ℹ️  Scans all local 'src/' and 'release/install/' packages, validates all")
    print("        dependencies, and prints a colored report showing which dependencies")
    print("        are satisfied (💚), missing (❤️), or have a version mismatch (❤️).")
    print("-" * 60)
    print("  index release")
    print("    📜 Lists ALL available packages from all configured GitHub repositories")
    print("        that have a compatible asset (for your OS/arch) on their latest release.")
    print("-" * 60)
    print("  index release <package-name>")
    print("    📜 Lists ALL available versions for a SINGLE package from GitHub Releases")
    print("        that have a compatible asset for the current system.")
    print("-" * 60)
    print("  git status")
    print("    🔄 Fetches and shows the detailed sync status (ahead, behind, local changes)")
    print("        for all repositories in the current directory and in 'src/'.")
    print("-" * 60)
    print("  git pull [origin]")
    print("    🔄 Pulls changes for all local repositories from the specified remote")
    print("        (defaults to 'origin').")
    print("-" * 60)
    print("  help, -h, --help")
    print("    ❓ Displays this help message.")
    print("="*60)

def run_command(command, cwd):
    """A helper function to run a shell command in a specific directory."""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip()}"
    except FileNotFoundError:
        return "Error: Git command not found."

import re # Make sure this is at the top of your file
import os
# Your other functions...

def get_repo_sort_key(repo_dict):
    """
    Creates a sort key for a repo. It sorts by the first remote's owner,
    then by the repo name, all case-insensitive.
    """
    remotes = repo_dict.get('remotes')
    primary_owner = '~~~~~'  # Default sort key to push items with no remotes to the end

    if remotes:  # Make sure the remotes list is not empty
        primary_owner = remotes[0].get('owner', '~~~~~') # Get owner of the first remote

    repo_name = repo_dict.get('name', '')

    # Return a tuple: this sorts by owner first, then by name.
    # .lower() ensures sorting is case-insensitive (e.g., 'A' and 'a' are treated the same).
    return (primary_owner.lower(), repo_name.lower())

def _ensure_github_auth():
    """Check if GitHub CLI is authenticated, and prompt login if not."""
    try:
        # Check if gh is installed
        result = subprocess.run(['gh', '--version'], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            print("GitHub CLI (gh) is not installed. Please install it first.")
            return False
            
        # Check if authenticated
        result = subprocess.run(['gh', 'auth', 'status'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("GitHub CLI is already authenticated.")
            return True
        else:
            print("GitHub CLI is not authenticated. Starting authentication...")
            # Run gh auth login interactively
            result = subprocess.run(['gh', 'auth', 'login'], timeout=300)
            return result.returncode == 0
            
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        print("Failed to check GitHub authentication status.")
        return False

def _run_git_command(command, cwd):
    """Helper to run a Git command and return its stripped output, handling errors."""
    try:
        # Using a timeout is safer for network operations like fetch
        result = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=15  # 15-second timeout
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        # Log error or return None
        return None
    except FileNotFoundError:
        # Git command not found or cwd is invalid
        return None

def _get_remote_details(cwd):
    """
    Parses `git remote -v` to get a dict of {name: {'owner': owner}}.
    """
    remote_output = _run_git_command(['git', 'remote', '-v'], cwd)
    if not remote_output:
        return {}

    remotes = {}
    # Regex to capture owner from ssh (git@github.com:OWNER/...) or https (https://github.com/OWNER/...)
    url_pattern = re.compile(r'(?:[:/])([^/]+)/([^/.]+)(?:\.git)?$')

    for line in remote_output.splitlines():
        if '(fetch)' not in line:
            continue

        try:
            name, url, _ = line.split()
            if name not in remotes:
                owner = '?'
                match = url_pattern.search(url)
                if match:
                    owner = match.group(1)  # Get the first capture group (the owner)
                remotes[name] = {'owner': owner}
        except ValueError:
            continue # Skip malformed lines

    return remotes

def _get_git_status(cwd, branch, remote_name):
    """Compares local HEAD to a specific remote branch and returns a status string."""
    remote_branch = f"{remote_name}/{branch}"

    # Check if the remote tracking branch exists
    if _run_git_command(['git', 'show-ref', '--verify', '--quiet', f'refs/remotes/{remote_branch}'], cwd) is None:
        return f"No remote '{branch}'"

    # Get ahead/behind counts using git rev-list
    counts_output = _run_git_command(['git', 'rev-list', '--left-right', '--count', f'HEAD...{remote_branch}'], cwd)
    if counts_output is None:
        return "Compare failed"

    try:
        ahead_str, behind_str = counts_output.split('\t')
        ahead = int(ahead_str)
        behind = int(behind_str)
    except Exception:
        return "Parse failed"

    # Format the status string
    if ahead > 0 and behind > 0:
        return f"Diverged (A {ahead}, B {behind})"
    elif ahead > 0:
        return f"Ahead {ahead}"
    elif behind > 0:
        return f"Behind {behind}"
    else:
        return "Up-to-date"

def _get_local_changes(cwd):
    """Gets a short summary of local uncommitted changes."""
    status_output = _run_git_command(['git', 'status', '--porcelain'], cwd)
    if status_output is None:
        return "Git Error"
    if not status_output:
        return "No changes"

    # Provide a summary similar to your desired format
    changed_files = 0
    untracked_files = 0
    for line in status_output.splitlines():
        if line.startswith('??'):
            untracked_files += 1
        else:
            changed_files += 1

    parts = []
    if changed_files > 0:
        # Try to get the user's diffstat format
        diff_stat = _run_git_command(['git', 'diff', '--shortstat', 'HEAD'], cwd)
        if diff_stat:
            # " 1 file changed, 53 insertions(+), 12 deletions(-)" -> "1 file, 53+, 12-"
            stat_summary = diff_stat.strip().replace(" changed", "").replace(" files", "f").replace(" file", "f").replace(" insertions", "").replace(" insertion", "").replace(" deletions", "").replace(" deletion", "").replace("(", "").replace(")", "")
            parts.append(stat_summary)
        else:
            parts.append(f"{changed_files} modified") # Fallback

    if untracked_files > 0:
        parts.append(f"{untracked_files} untracked")

    return ", ".join(parts)

def process_repo(repo_path, pull_mode, origin="origin"):
    """
    Processes a single Git repository.
    - IF pull_mode=True: Attempts to pull the specified 'origin' and returns a simple status dict.
    - IF pull_mode=False: Fetches all remotes, checks local changes, and compares HEAD to ALL remote branches.
    """

    repo_name = os.path.basename(repo_path)

    # --- PATH 1: PULL MODE ---
    # This logic now executes, returns the expected dict, and exits the function.
    if pull_mode:
        # Get owner details, since the summary print requires it.
        remote_details = _get_remote_details(repo_path)
        owner = remote_details.get(origin, {}).get('owner') # Safely get owner for the target origin

        try:
            # Attempt to get the current branch name to pull into.
            current_branch = _run_git_command(['git', 'symbolic-ref', '--short', 'HEAD'], repo_path)
            if not current_branch:
                raise Exception("Detached HEAD: Cannot pull.") # Fail cleanly if detached

            # Run the git pull command against the specified origin and branch.
            # Using --ff-only is safest: it won't create merge commits and will fail if the pull isn't a simple fast-forward.
            pull_result = _run_git_command(
                ['git', 'pull', origin, current_branch, '--ff-only', '--quiet'],
                repo_path
            )

            # _run_git_command should return stdout. If it's quiet, a successful pull returns an empty string
            # or a summary, while "Already up to date." is a specific message.
            # NOTE: git pull writes "Already up to date." to STDOUT, not stderr.
            pull_result = pull_result.strip()

            if "Already up to date." in pull_result or pull_result == "":
                message = "Already up to date."
            else:
                # Any other output implies changes were pulled.
                message = pull_result.split('\n')[-1].strip() # Get summary line

            return {
                'name': repo_name,
                'owner': owner,
                'status': 'Success',
                'message': message
            }

        except Exception as e:
            # This catches errors from _run_git_command (like a non-zero exit code) or our Exception above.
            # We need to parse the error message from git.
            error_message = str(e)
            if hasattr(e, 'stderr') and e.stderr: # Handle subprocess.CalledProcessError
                error_message = e.stderr.decode().strip().split('\n')[-1] # Get last meaningful error line
            elif hasattr(e, 'stdout') and e.stdout: # Handle cases where git pull fails but writes to stdout
                error_message = e.stdout.decode().strip().split('\n')[-1]

            # Clean common git error prefixes
            if error_message.startswith('fatal:'):
                error_message = error_message[len('fatal: '):]

            return {
                'name': repo_name,
                'owner': owner,
                'status': 'Fail',
                'message': error_message
            }

    # --- PATH 2: STATUS CHECK MODE ---
    # This existing logic will only run if pull_mode is False.
    # This block correctly returns the detailed status report.

    # 1. Get current branch
    current_branch = _run_git_command(['git', 'symbolic-ref', '--short', 'HEAD'], repo_path)
    if not current_branch:
        # Handle detached HEAD state
        current_branch = _run_git_command(['git', 'rev-parse', '--short', 'HEAD'], repo_path) or "DETACHED"
        if "DETACHED" in current_branch:
            return {
                'name': repo_name, # Use name we defined earlier
                'branch': current_branch,
                'changes': 'N/A (Detached HEAD)',
                'remotes': []
            }

    # 2. Get local changes
    local_changes = _get_local_changes(repo_path)

    # 3. Get all remotes and their owners
    remote_details = _get_remote_details(repo_path)
    if not remote_details:
        return {
            'name': repo_name,
            'branch': current_branch,
            'changes': local_changes,
            'remotes': [{'name': 'N/A', 'owner': 'N/A', 'status': 'No remotes configured'}]
        }

    # 4. Fetch ALL remotes to get up-to-date info.
    _run_git_command(['git', 'fetch', '--all', '--quiet'], repo_path)

    # 5. Build the final remotes list with status for each one
    remotes_list = []
    for remote_name, details in remote_details.items():
        # Check status of our local branch against this remote's version
        status_str = _get_git_status(repo_path, current_branch, remote_name)

        remotes_list.append({
            'name': remote_name,
            'owner': details['owner'],
            'status': status_str
        })

    # Sort remotes alphabetically
    remotes_list.sort(key=lambda x: x['name'])

    # 6. Return the complete data structure (for status check mode)
    return {
        'name': repo_name,
        'branch': current_branch,
        'changes': local_changes,
        'remotes': remotes_list
    }

def manage_git_repos(pull_mode, origin="origin"):
    """
    Manages Git repositories in the current directory and './src'.
    - Default: Checks status.
    - With '--pull' argument: Pulls and provides a clean summary.
    """
    # ... (The code to find repo_paths remains unchanged) ...
    repo_paths = []
    current_dir = os.getcwd()
    if os.path.isdir(os.path.join(current_dir, '.git')):
        repo_paths.append(current_dir)

    src_path = os.path.join(current_dir, 'src')
    if os.path.isdir(src_path):
        for dir_name in os.listdir(src_path):
            repo_path = os.path.join(src_path, dir_name)
            if os.path.isdir(os.path.join(repo_path, '.git')):
                repo_paths.append(repo_path)

    if not repo_paths:
        print("No Git repositories found.")
        return

    all_results = list(concurrent.futures.ThreadPoolExecutor().map(
        lambda path: process_repo(path, pull_mode=pull_mode, origin=origin), repo_paths
    ))
    all_results.sort(key=get_repo_sort_key)

    if pull_mode:
        # ... (The pull_mode logic remains unchanged) ...
        print("\n--- Pull Summary ---")
        summary_names = [f"{res['name']} ({res['owner']})" if res.get('owner') else res['name'] for res in all_results]
        max_name = max(len(name) for name in summary_names)
        for i, res in enumerate(all_results):
            # 1. Use .get('status')
            # If 'status' key is missing, .get() returns None.
            # Comparing (None == 'Success') is safely False, so icon correctly becomes "❌".
            icon = "✅" if res.get('status') == 'Success' else "❌"

            # 2. Make the message safe too, providing a default error message
            # in case 'message' is also missing or res itself is None.
            if res:
                message = res.get('message', 'Processing failed: No message returned.')
            else:
                # This handles cases where process_repo returned None entirely
                message = 'CRITICAL ERROR: Worker process returned None.'
                icon = "❌"

            print(f"{icon} {summary_names[i]:<{max_name}}  ->  {message}")
    else:
        # 1. Discover all unique remote names to use as column headers
        # We must loop through all results first to see what columns we need to create.
        all_remote_names = set()
        for repo in all_results:
            for remote in repo.get('remotes', []):
                if 'name' in remote:
                    all_remote_names.add(remote['name'])

        # Create a consistent, sorted list of remote names (e.g., ['origin', 'raion'])
        # This ensures the columns are always in the same order.
        sorted_remote_names = sorted(list(all_remote_names))

        # 2. Build the display_rows data structure with dynamic remote keys
        display_rows = []
        for repo in all_results:
            # Basic info for the static columns
            row_data = {
                'name': repo.get('name', '?'),
                'branch': repo.get('branch', '?'),
            }
            local_changes = repo.get('changes', 'No changes')

            # Create a lookup map for the remotes this specific repo has
            repo_remotes_map = {r.get('name'): r for r in repo.get('remotes', [])}

            # 3. Populate the data for each dynamic remote column
            for remote_name in sorted_remote_names:
                if remote_name in repo_remotes_map:
                    # This repo HAS this remote. Build the status string for this one cell.
                    remote = repo_remotes_map[remote_name]
                    owner = remote.get('owner', '?')
                    r_status = remote.get('status', 'Unknown')
                    cell_string = f"{owner} - {r_status}, {local_changes}"
                    row_data[remote_name] = cell_string
                else:
                    # This repo does NOT have this remote (e.g., raisin_third_party_robot only has origin).
                    # Fill the cell with a placeholder so the table aligns.
                    row_data[remote_name] = "-"

            display_rows.append(row_data)

        # 4. Define the headers dictionary, which is now also dynamic
        headers = {
            "REPOSITORY": "name",
            "BRANCH": "branch",
        }
        # Add the remote names as headers (e.g., "ORIGIN", "RAION")
        for r_name in sorted_remote_names:
            headers[r_name] = r_name  # Header key (e.g., "ORIGIN"), Data key (e.g., "origin")


        # 5. Calculate max widths (This logic is unchanged, it works perfectly with the new headers)
        max_widths = {}
        for header_text, key in headers.items():
            header_width = get_display_width(header_text)
            max_data_width = 0
            if display_rows:
                max_data_width = max(get_display_width(row.get(key, '')) for row in display_rows)
            max_widths[key] = max(header_width, max_data_width)

        # 6. Build and print the header row (Unchanged)
        header_parts = []
        for header_text, key in headers.items():
            width = max_widths[key]
            header_parts.append(header_text + ' ' * (width - get_display_width(header_text)))
        header_str = " | ".join(header_parts)
        print(header_str)
        print('-' * get_display_width(header_str))

        # 7. Build and print each data row (Unchanged)
        # This will now print a row with the correct number of perfectly padded columns.
        for row in display_rows:
            row_parts = []
            for header_text, key in headers.items():
                width = max_widths[key]
                value = row.get(key, '')
                padded_value = value + ' ' * (width - get_display_width(value))
                row_parts.append(padded_value)
            print(" | ".join(row_parts))


def list_all_available_packages():
    """
    Scans all repository.yaml files, finds all available packages, and lists
    their most recent release versions that have a valid asset for the current system.
    """
    print("🔍 Finding all available packages and their latest versions with compatible assets...")
    script_dir_path = Path(script_directory)
    all_repositories = {}

    # --- Get System Info for Asset Matching ---
    try:
        print(f"ℹ️  Checking for assets compatible with: {os_type}-{os_version}-{architecture}")
    except FileNotFoundError:
        print("❌ Error: Could not determine OS information from /etc/os-release.")
        return

    # Load all repository configurations
    repo_files = sorted(list(set(glob.glob(str(script_dir_path / '*_repositories.yaml')) + glob.glob(str(script_dir_path / 'repositories.yaml')))))
    for file_path in repo_files:
        with open(file_path, 'r') as f:
            repo_data = yaml.safe_load(f)
            if repo_data:
                all_repositories.update(repo_data)

    if not all_repositories:
        print("🤷 No packages found in any repositories.yaml files.")
        return

    # Load GitHub tokens for API requests
    tokens = {}
    secrets_path = script_dir_path / 'secrets.yaml'
    if secrets_path.is_file():
        with open(secrets_path, 'r') as f:
            secrets = yaml.safe_load(f)
            tokens = secrets.get('gh_tokens', {})

    session = requests.Session()

    def get_versions_for_package(package_name):
        """Fetches and processes release versions with valid assets for a single package."""
        repo_info = all_repositories.get(package_name)
        if not repo_info or 'url' not in repo_info:
            return package_name, ["(No repository URL found)"]

        git_url = repo_info['url']
        match = re.search(r'git@github.com:(.*)/(.*)\.git', git_url)
        if not match:
            return package_name, ["(Could not parse repository URL)"]

        owner, repo_name = match.groups()
        token = tokens.get(owner)
        headers = {'Accept': 'application/vnd.github.v3+json'}
        if token:
            headers['Authorization'] = f'token {token}'

        try:
            api_url = f"https://api.github.com/repos/{owner}/{repo_name}/releases"
            response = session.get(api_url, headers=headers, timeout=10)
            response.raise_for_status()
            releases_list = response.json()

            if not releases_list:
                return package_name, ["(No releases found)"]

            available_versions = []
            for release in releases_list:
                tag = release.get('tag_name')
                if not tag or release.get('prerelease'):
                    continue
                try:
                    version_obj = parse_version(tag)
                    # Construct the expected asset filenames
                    expected_asset_release = f"{package_name}-{os_type}-{os_version}-{architecture}-release-{tag}.zip"
                    expected_asset_debug = f"{package_name}-{os_type}-{os_version}-{architecture}-debug-{tag}.zip"

                    # Check for a matching asset
                    for asset in release.get('assets', []):
                        if asset['name'] == expected_asset_release or asset['name'] == expected_asset_debug:
                            available_versions.append(version_obj)
                            break
                except InvalidVersion:
                    continue

            if not available_versions:
                return package_name, ["(No compatible assets found)"]

            # Return the top 3 newest versions that have assets
            sorted_versions = sorted(available_versions, reverse=True)
            return package_name, [str(v) for v in sorted_versions[:3]]

        except requests.exceptions.RequestException:
            return package_name, ["(API Error)"]

    # --- Fetch versions concurrently for all packages ---
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_package = {executor.submit(get_versions_for_package, name): name for name in all_repositories.keys()}
        for future in concurrent.futures.as_completed(future_to_package):
            name, version_list = future.result()
            results[name] = version_list

    # --- Print the formatted results ---
    print("\nAvailable packages and latest versions:")
    for package_name in sorted(results.keys()):
        versions_str = ", ".join(results[package_name])
        print(f"  - {package_name}: {versions_str}")


def list_github_release_versions(package_name: str):
    """
    Fetches and lists all available release versions of a package from its GitHub
    repository that have a valid asset for the current system.
    """
    print(f"🔍 Finding available versions with assets for '{package_name}'...")
    script_dir_path = Path(script_directory)

    # --- 1. Get System Info for Asset Matching ---
    try:
        print(f"ℹ️  Checking for assets compatible with: {os_type}-{os_version}-{architecture}")
    except FileNotFoundError:
        print("❌ Error: Could not determine OS information from /etc/os-release.")
        return

    # --- 2. Load Repository and Secrets Configuration ---
    all_repositories = {}
    repo_files = sorted(list(set(glob.glob(str(script_dir_path / '*_repositories.yaml')) + glob.glob(str(script_dir_path / 'repositories.yaml')))))
    for file_path in repo_files:
        with open(file_path, 'r') as f:
            repo_data = yaml.safe_load(f)
            if repo_data:
                all_repositories.update(repo_data)

    tokens = {}
    secrets_path = script_dir_path / 'secrets.yaml'
    if secrets_path.is_file():
        with open(secrets_path, 'r') as f:
            secrets = yaml.safe_load(f)
            tokens = secrets.get('gh_tokens', {})

    # --- 3. Find the repository URL for the package ---
    repo_info = all_repositories.get(package_name)
    if not repo_info or 'url' not in repo_info:
        print(f"❌ Error: No repository URL found for '{package_name}' in any repositories.yaml file.")
        return

    # --- 4. Parse Owner/Repo from URL ---
    git_url = repo_info['url']
    match = re.search(r'git@github.com:(.*)/(.*)\.git', git_url)
    if not match:
        print(f"❌ Error: Could not parse GitHub owner/repo from URL '{git_url}'.")
        return

    owner, repo_name = match.groups()

    # --- 5. Query the GitHub API ---
    session = requests.Session()
    token = tokens.get(owner)
    if token:
        session.headers.update({'Authorization': f'token {token}', 'Accept': 'application/vnd.github.v3+json'})

    try:
        api_url = f"https://api.github.com/repos/{owner}/{repo_name}/releases"
        response = session.get(api_url)
        response.raise_for_status()
        releases_list = response.json()

        if not releases_list:
            print(f"🤷 No releases found for repository '{owner}/{repo_name}'.")
            return

        # --- 6. Parse, Match Assets, Sort, and Display Versions ---
        available_versions = []
        for release in releases_list:
            tag = release.get('tag_name')
            if not tag or release.get('prerelease'):
                continue

            try:
                version_obj = parse_version(tag)
                # Construct the expected asset filenames for release and debug builds
                expected_asset_release = f"{package_name}-{os_type}-{os_version}-{architecture}-release-{tag}.zip"
                expected_asset_debug = f"{package_name}-{os_type}-{os_version}-{architecture}-debug-{tag}.zip"

                # Check if any asset in this release matches our expected filename
                for asset in release.get('assets', []):
                    if asset['name'] == expected_asset_release or asset['name'] == expected_asset_debug:
                        available_versions.append(version_obj)
                        break # Found a valid asset, no need to check others in this release
            except InvalidVersion:
                continue

        if not available_versions:
            print(f"🤷 No releases with compatible assets found for '{package_name}'.")
            return

        # Sort from newest to oldest
        sorted_versions = sorted(available_versions, reverse=True)

        print(f"Available versions for {package_name} ({owner}/{repo_name}):")
        for v in sorted_versions:
            print(f"  {v}")

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"❌ Error: Repository '{owner}/{repo_name}' not found on GitHub or you lack permissions.")
        else:
            print(f"❌ HTTP Error fetching release data: {e}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error: {e}")
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")


def _read_os_release() -> Dict[str, str]:
    """
    Best-effort reader for Linux /etc/os-release. Uses platform.freedesktop_os_release()
    when available; falls back to parsing the file manually. Returns {} on failure.
    """
    # Python 3.10+ provides this:
    if hasattr(platform, "freedesktop_os_release"):
        try:
            return platform.freedesktop_os_release()
        except Exception:
            pass

    # Manual fallback for older Pythons
    data: Dict[str, str] = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip().strip('"')
                data[k] = v
    except Exception:
        pass
    return data

def _normalize_arch(arch: str) -> str:
    """
    Normalize common architecture names across platforms.
    """
    m = (arch or "").lower()
    mapping = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86_64": "x86_64",
        "i386": "x86",
        "i686": "x86",
        "aarch64": "arm64",
        "arm64": "arm64",
        "armv7l": "armv7l",
        "armv6l": "armv6l",
        "ppc64le": "ppc64le",
        "ppc64": "ppc64",
        "s390x": "s390x",
    }
    return mapping.get(m, arch)

def get_os_info() -> Tuple[str, str, str, str, str, dict]:
    """
    Returns (os_type, architecture, os_version) across Linux/macOS/Windows.

    - os_type:
        Linux -> distro ID if available (e.g., 'ubuntu', 'fedora'), otherwise 'linux'
        macOS -> 'macos'
        Windows -> 'windows'
        Other/Unix -> platform.system().lower()
    - architecture: normalized machine type (e.g., 'x86_64', 'arm64')
    - os_version:
        Linux -> VERSION_ID from os-release if available, else kernel release
        macOS -> product version (e.g., '14.5'), else kernel release
        Windows -> major.minor.build from sys.getwindowsversion(), else win32_ver()/release()
    """
    system = platform.system()
    arch = _normalize_arch(platform.machine())
    vs_path2 = ""
    ninja_path2 = ""
    developer_env2 = dict()

    if system == "Linux":
        osr = _read_os_release()
        os_type2 = (osr.get("ID") or "linux").lower()
        os_version2 = osr.get("VERSION_ID") or platform.release()

    elif system == "Darwin":
        os_type2 = "macos"
        mac_release, _, _ = platform.mac_ver()
        os_version2 = mac_release or platform.release()

    elif system == "Windows":
        vs_path2, ninja_path2, developer_env2 = find_build_tools("amd64")
        os_type2 = "windows"
        try:
            win = sys.getwindowsversion()  # (major, minor, build, platform, service_pack)
            # os_version2 = f"{win.major}.{win.minor}.{win.build}"
            os_version2 = "10or11"
        except Exception:
            release, version, _, _ = platform.win32_ver()
            os_version2 = version or release or platform.release()

    else:  # e.g., FreeBSD, OpenBSD, SunOS, etc.
        os_type2 = system.lower() if system else "unknown"
        os_version2 = platform.release()

    return os_type2, arch, os_version2, vs_path2, ninja_path2, developer_env2

def find_target_yamls(priority_dir: Path, fallback_dir: Path) -> List[Tuple[str, Path, str]]:
    """
    Scans directories for 'release.yaml' files, tagging their origin.
    (This function is unchanged from the previous step.)
    """
    targets: List[Tuple[str, Path, str]] = []
    found_packages: Set[str] = set()

    # 1. Scan the PRIORITY directory first (src)
    if priority_dir.is_dir():
        for item in priority_dir.iterdir():
            if item.is_dir():
                yaml_file = item / "release.yaml"
                if yaml_file.is_file():
                    pkg_name = item.name
                    targets.append((pkg_name, yaml_file, "source"))
                    found_packages.add(pkg_name)
    else:
        print(f"Warning: Priority directory not found, skipping: {priority_dir}")

    # 2. Scan the FALLBACK directory (release/install)
    if fallback_dir.is_dir():
        for item in fallback_dir.iterdir():
            if item.is_dir():
                pkg_name = item.name
                if pkg_name not in found_packages:
                    yaml_file_release = item / os_type / os_version / architecture / "release/release.yaml"
                    yaml_file_debug = item / os_type / os_version / architecture / "debug/release.yaml"
                    if yaml_file_release.is_file():
                        targets.append((pkg_name, yaml_file_release, "release"))
                    elif yaml_file_debug.is_file():
                        targets.append((pkg_name, yaml_file_release, "release"))
    else:
        print(f"Warning: Fallback directory not found, skipping: {fallback_dir}")

    return targets

def parse_package_yaml(pkg_name: str, yaml_path: Path) -> Tuple[str, str, Optional[List[str]]]:
    """
    Worker function for Pass 1 (Parse).
    Parses a single YAML file and returns the RAW dependency list.

    Returns:
        A tuple: (package_name, version_string, raw_deps_list_or_None)
    """
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            return (pkg_name, "ERROR", ["Invalid or empty YAML"])

        version = str(data.get('version', 'N/A'))

        # Get the raw list of dependencies (or None)
        deps_list: Optional[List[str]] = data.get('dependencies')

        return (pkg_name, version, deps_list)

    except yaml.YAMLError as e:
        return (pkg_name, "ERROR", [f"YAML Parse Error: {e}"])
    except Exception as e:
        return (pkg_name, "ERROR", [f"File Read Error: {e}"])

def run_parallel_parse(targets: List[Tuple[str, Path, str]]) -> List[Tuple[str, str, Optional[List[str]], str]]:
    """
    Manages the first thread pool (Pass 1) to parse all files.

    Returns:
        List of tuples: [(pkg_name, ver_str, raw_deps_list, origin_tag), ...]
    """
    all_parse_results = []

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures_map = {
            executor.submit(parse_package_yaml, pkg_name, yaml_path): (pkg_name, origin_tag)
            for pkg_name, yaml_path, origin_tag in targets
        }

        for future in concurrent.futures.as_completed(futures_map):
            pkg_name_for_error, origin = futures_map[future]
            try:
                # parser_result is (pkg_name, ver, deps_list)
                parser_result = future.result()
                all_parse_results.append(parser_result + (origin,))
            except Exception as e:
                print(f"Critical error processing package {pkg_name_for_error}: {e}")
                all_parse_results.append((pkg_name_for_error, "CRITICAL ERROR", [str(e)], origin))

    return all_parse_results

# --- Pass 2: Validation Functions ---

def process_and_color_deps(
        pkg_name: str,
        version: str,
        deps_list: Optional[List[str]],
        origin: str,
        package_db: Dict[str, str]
) -> Tuple[str, str, str, str]:
    """
    Worker function for Pass 2 (Validate).
    Takes one package's raw deps and validates them against the complete DB.

    Returns:
        Final tuple for printing: (pkg_name, version, colored_deps_string, origin)
    """

    # If this package itself failed parsing (Pass 1), its version is "ERROR"
    # and its "deps_list" is actually the error message. Color it all red.
    if version == "ERROR":
        deps_str = f"{Colors.RED}{', '.join(deps_list or ['Unknown Error'])}{Colors.RESET}"
        return (pkg_name, version, deps_str, origin)

    # If parsing was successful but there are no dependencies, return "None"
    if not deps_list:
        return (pkg_name, version, "None", origin)

    # Begin validating the list of dependencies one by one
    colored_deps = []
    for dep_spec_string in deps_list:
        try:
            # Use 'packaging' library to parse the requirement string
            # e.g., "pkg_b>=1.0.0,<2.0.0" or just "pkg_c"
            req = Requirement(dep_spec_string)

        except (InvalidSpecifier, Exception):
            # Handle malformed requirement strings like "pkg_b>>>1"
            colored_deps.append(f"{Colors.RED}{dep_spec_string} (Invalid Spec){Colors.RESET}")
            continue

        # 1. Check if the dependency EXISTS in our database
        if req.name not in package_db:
            colored_deps.append(f"{Colors.RED}{dep_spec_string} (Missing){Colors.RESET}")
            continue

        # 2. If it exists, check if the found version MATCHES the specifier
        try:
            actual_version_str = package_db[req.name]
            actual_version = Version(actual_version_str)

            # This is the core check using the 'packaging' library:
            # req.specifier is a SpecifierSet object (e.g., ">=1.0.0,<2.0.0")
            # The 'in' operator checks if the Version object satisfies the constraints.
            # If the specifier is empty (e.g., just "pkg_c"), it matches any version.
            if actual_version in req.specifier:
                colored_deps.append(f"{Colors.GREEN}{dep_spec_string}{Colors.RESET}")
            else:
                # Found, but version is wrong (e.g., we require >=1.0 but found 0.9)
                colored_deps.append(f"{Colors.RED}{dep_spec_string} (Wrong Version){Colors.RESET}")

        except InvalidVersion:
            # The dependency we found has an invalid version (e.g., "N/A" or "ERROR")
            # It cannot satisfy any version requirement.
            colored_deps.append(f"{Colors.RED}{dep_spec_string} (Dep has Invalid Ver: {actual_version_str}){Colors.RESET}")
        except Exception as e:
            # Catch-all for other unexpected validation errors
            colored_deps.append(f"{Colors.RED}{dep_spec_string} (Check Error: {e}){Colors.RESET}")

    # Join all the individually colored strings with a comma
    final_deps_str = ", ".join(colored_deps)
    return (pkg_name, version, final_deps_str, origin)


def run_parallel_validation(
        all_pkg_data: List[Tuple[str, str, Optional[List[str]], str]],
        package_db: Dict[str, str]
) -> List[Tuple[str, str, str, str]]:
    """
    Manages the second thread pool (Pass 2) to validate all dependencies.
    """
    final_print_data = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures_map = {
            executor.submit(process_and_color_deps, name, ver, deps, origin, package_db): name
            for name, ver, deps, origin in all_pkg_data
        }

        for future in concurrent.futures.as_completed(futures_map):
            try:
                # Result is the final 4-tuple for printing
                result = future.result()
                final_print_data.append(result)
            except Exception as e:
                pkg_name = futures_map[future]
                print(f"Critical error during validation for {pkg_name}: {e}")

    return final_print_data


# --- Printing Function ---

def print_aligned_results(results: List[Tuple[str, str, str, str]]):
    """
    Takes the final (colored) results and prints them in an aligned format.
    This logic handles the color codes in the package prefix correctly.
    """
    if not results:
        print("No package data to display.")
        return

    # --- Alignment Calculation (Pre-pass) ---
    processed_data = []
    max_name_len = 0
    max_ver_len = 0

    for name, ver, colored_deps_str, origin in results:
        raw_full_name = f"({origin}) {name}"
        processed_data.append((raw_full_name, ver, colored_deps_str, origin))

        if len(raw_full_name) > max_name_len:
            max_name_len = len(raw_full_name)
        if len(ver) > max_ver_len:
            max_ver_len = len(ver)


    # --- Print Header and Results ---
    print("\n--- Package Version Report ---")
    for raw_name, ver, colored_deps_str, origin in processed_data:

        padded_raw_name = f"{raw_name:<{max_name_len}}"

        if origin == "source":
            color = Colors.GREEN
            tag = "(source)"
        else: # origin == "release"
            color = Colors.BLUE
            tag = "(release)"

        # Replace the raw tag with the colored one to preserve alignment
        colored_name = padded_raw_name.replace(
            tag,
            f"{color}{tag}{Colors.RESET}"
        )

        padded_ver = f"{ver:<{max_ver_len}}"

        # Print the final line. The dependency string is the last column,
        # so its variable visual length (due to color codes) is fine.
        print(f"{colored_name} , version: {padded_ver} , dependencies: {colored_deps_str}")



if __name__ == '__main__':
    script_directory = Path(os.path.dirname(os.path.realpath(__file__))).as_posix()
    os_type, architecture, os_version, visual_studio_path, ninja_path, developer_env = get_os_info()

    delete_directory(os.path.join(script_directory, 'temp'))

    always_yes = '--yes' in sys.argv
    if always_yes:
        sys.argv.remove('--yes')

    # Display help if no arguments are given or if help is explicitly requested
    if len(sys.argv) == 2 and sys.argv[1] in ['help', '-h', '--help']:
        print_help()
        exit(0)

    if len(sys.argv) == 1 or sys.argv[1] == 'setup' or sys.argv[1] == 'build':
        targets = sys.argv[2:]

        # 1. Find and parse all YAML files to create a master dictionary
        if len(sys.argv) > 3 and (Path(script_directory) / 'src' / sys.argv[2]).exists():
            build_pattern =[name for name in os.listdir(Path(script_directory) / 'src' / sys.argv[2])
                            if os.path.isdir(os.path.join(Path(script_directory) / 'src' / sys.argv[2], name))]
        else:
            all_build_maps = {}
            yaml_search_path = os.path.join(script_directory, 'src', '**', 'RAISIN_BUILD_TARGETS.yaml')

            for filepath in glob.glob(yaml_search_path, recursive=True):
                with open(filepath, 'r') as f:
                    try:
                        # Load the YAML content and merge it into the master dictionary
                        yaml_content = yaml.safe_load(f)
                        if yaml_content:
                            all_build_maps.update(yaml_content)
                    except yaml.YAMLError as e:
                        print(f"Warning: Could not parse YAML file {filepath}. Error: {e}")

            # 2. Collect build patterns based on the input targets
            found_patterns = []
            for target in targets:
                # Use .get() to find patterns for the target; returns an empty list if not found
                patterns_for_target = all_build_maps.get(target, [])
                found_patterns.extend(patterns_for_target)

            # 3. Update the global build_pattern variable
            build_pattern = found_patterns

        if not build_pattern:
            print("🛠️ building all patterns")
        else:
            print(f"🛠️ building the following targets: {build_pattern}")

        setup()

    elif sys.argv[1] == 'release':
        # Check if any arguments are provided after 'release'
        if len(sys.argv) < 3:
            print("❌ Error: Please specify at least one target to release.")
        else:
            # Check if the last argument is a specific build type
            if sys.argv[-1].lower() in ('release', 'debug'):
                build_type = sys.argv[-1].lower()
                # All arguments between 'release' and the final build type are targets
                targets = sys.argv[2:-1]
            else:
                # Otherwise, default the build type to 'release'
                build_type = 'release'
                # All arguments after 'release' are targets
                targets = sys.argv[2:]

            # After parsing, ensure we actually have targets to build
            if not targets:
                print("❌ Error: No build targets specified.")
            else:
                print(f"Starting release with build type: '{build_type}'")
                # Iterate over each target and call the release function
                for target in targets:
                    print(f"--> Releasing target: {target}")
                    release(target, build_type)

    elif sys.argv[1] == 'index':
        if len(sys.argv) >= 3 and sys.argv[2] == 'release':
            # Case 1: Package name is provided, list its versions
            if len(sys.argv) == 4:
                package_name = sys.argv[3]
                list_github_release_versions(package_name)
            # Case 2: No package name, list all available packages
            elif len(sys.argv) == 3:
                list_all_available_packages()
            else:
                print("❌ Error: Invalid 'index versions' command. Provide zero or one package name.")
        elif len(sys.argv) >= 3 and sys.argv[2] == 'local':
            targets_to_process = find_target_yamls(Path(script_directory) / 'src',
                                                   Path(script_directory) / 'release' / 'install')

            if not targets_to_process:
                print("Found no packages with release.yaml files in specified locations.")

            # 2. PASS 1: Run parallel parsing
            # all_parse_results format: [(name, ver, raw_deps_list, origin), ...]
            all_parse_results = run_parallel_parse(targets_to_process)

            # 3. Build the Package Database for validation
            # This map contains ONLY valid packages that can be dependencies.
            package_db: Dict[str, str] = {}
            for name, ver, deps_list, origin in all_parse_results:
                if ver not in ("ERROR", "N/A"):
                    package_db[name] = ver

            # 4. PASS 2: Run parallel validation using the database
            # final_print_data format: [(name, ver, colored_deps_str, origin), ...]
            final_print_data = run_parallel_validation(all_parse_results, package_db)

            # 5. Sort the final list alphabetically
            final_print_data.sort(key=lambda x: x[0])

            # 6. Print the aligned, colored results
            print_aligned_results(final_print_data)
        else:
            print("❌ Error: Invalid 'index' command. Use: index 'remote' or index 'local'")

    elif sys.argv[1] == 'install':
        # Set default build type
        build_type = 'release'

        # Get all potential targets (all arguments after 'install')
        targets = sys.argv[2:]

        # Check if the last argument specifies the build type
        if targets and targets[-1] in ['release', 'debug']:
            # If it does, set the build type
            build_type = targets[-1]
            # And remove it from the list of targets
            targets = targets[:-1]

        # Call the install function with the parsed arguments
        install(targets, build_type)

    elif len(sys.argv) >= 3 and sys.argv[1] == 'git':
        # Ensure GitHub authentication before any git operations
        if not _ensure_github_auth():
            print("Warning: GitHub authentication failed. Some operations may not work properly.")
            
        if sys.argv[2] == 'status':
            manage_git_repos(pull_mode=False)
        if sys.argv[2] == 'pull':
            if len(sys.argv) >= 4:
                manage_git_repos(pull_mode=True, origin=sys.argv[3])
            else:
                manage_git_repos(pull_mode=True)

    else:
        print("❌ Error: No command-line arguments were provided.")

    if len(sys.argv) >= 2 and sys.argv[1] == 'build':
        build_types = sys.argv[2:]
        to_install = 'install' in build_types
        build_types = [bt for bt in build_types if bt != 'install']

        if not 'debug' in build_types and not 'release' in build_types:
            build_types.append('debug')

        for build_type in build_types:
            if build_type not in ['release', 'debug']:
                continue

            # 2. Run CMake
            build_type = build_type.lower()
            build_dir = Path(script_directory) / f'cmake-build-{build_type}'
            build_type = build_type.capitalize()
            delete_directory(build_dir)
            build_dir.mkdir(parents=True, exist_ok=True)
            print(f'building in {build_dir}, build type is {build_type}')

            # CORRECTED command list
            cmake_command = ["cmake",
                             "-G", "Ninja",
                             f"-DCMAKE_BUILD_TYPE={build_type.upper()}",
                             ".."]
            if platform.system().lower() == "linux":
                cmake_command = ["cmake",
                                 "-S", script_directory,
                                 "-G", "Ninja",
                                 "-B", build_dir / "build",
                                 f"-DCMAKE_BUILD_TYPE={build_type}"]
                subprocess.run(cmake_command, check=True, text=True)
                print("✅ CMake configuration successful.")
                print("🛠️  Building with Ninja...")
                core_count = int(os.cpu_count() / 2) or 4
                print(f"🔩 Using {core_count} cores for the build.")
                if to_install:
                    build_command = ["ninja", "install", f"-j{core_count}"]
                else:
                    build_command = ["ninja", f"-j{core_count}"]
                subprocess.run(build_command, cwd=build_dir / "build", check=True, text=True)

            else:
                cmake_command = ["cmake",
                                 "--preset", build_type.lower(),
                                 "-S", script_directory,
                                 "-B", build_dir / "build",
                                 f"-DCMAKE_TOOLCHAIN_FILE={script_directory}/vcpkg/scripts/buildsystems/vcpkg.cmake",
                                 "-DRAISIN_RELEASE_BUILD=ON"]
                subprocess.run(cmake_command, check=True, text=True, env=developer_env)
                print("✅ CMake configuration successful.")
                print("🛠️  Building with Ninja...")

                subprocess.run(
                    ["cmake", "--build", str(build_dir / "build"), "--parallel"],
                    check=True, text=True, env=developer_env
                )

                if to_install:
                    subprocess.run(
                        ["cmake", "--install", str(build_dir / "build")],
                        check=True, text=True, env=developer_env
                    )

        print("🎉🎉🎉 Building process finished successfully.")
