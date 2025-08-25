import os
import platform
import re
import shutil
import sys
from collections import defaultdict
import subprocess
from pathlib import Path
from platform import architecture
from typing import Union
import glob
import yaml
import fnmatch
from urllib.parse import urlparse
import concurrent.futures

from packaging.version import parse as parse_version, InvalidVersion
import zipfile
from packaging.specifiers import SpecifierSet
import requests


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

STRING_TYPES = ['std::string', 'std::u16string']

build_pattern = []

def is_root():
    """Check if the current user is root."""
    return os.geteuid() == 0

def delete_directory(directory):
    if os.path.exists(directory):
        shutil.rmtree(directory)

def create_service_file(srv_file, script_directory, project_directory):
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

    destination_file = os.path.join(script_directory, 'install', 'messages', project_name, 'srv', '')
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
    response_set_buffer_member_string = ""
    response_get_buffer_member_string = ""

    for bm in request_buffer_members:
        request_set_buffer_member_string += f"::raisin::setBuffer(buffer, {bm});\n"
        request_get_buffer_member_string += f"temp = ::raisin::getBuffer(temp, {bm});\n"

    for bm in response_buffer_members:
        response_set_buffer_member_string += f"::raisin::setBuffer(buffer, {bm});\n"
        response_get_buffer_member_string += f"temp = ::raisin::getBuffer(temp, {bm});\n"

    service_content = service_content.replace('@@REQUEST_SET_BUFFER_MEMBERS@@', request_set_buffer_member_string)
    modified_request_set_buffer_member_string = "\n".join("buffer = " + line for line in request_set_buffer_member_string.splitlines())
    service_content = service_content.replace('@@REQUEST_SET_BUFFER_MEMBERS2@@', modified_request_set_buffer_member_string)
    service_content = service_content.replace('@@REQUEST_GET_BUFFER_MEMBERS@@', request_get_buffer_member_string)
    service_content = service_content.replace('@@REQUEST_BUFFER_SIZE@@', "\n  ".join(request_buffer_size))

    service_content = service_content.replace('@@RESPONSE_SET_BUFFER_MEMBERS@@', response_set_buffer_member_string)
    modified_response_set_buffer_member_string = "\n".join("buffer = " + line for line in response_set_buffer_member_string.splitlines())
    service_content = service_content.replace('@@RESPONSE_SET_BUFFER_MEMBERS2@@', modified_response_set_buffer_member_string)
    service_content = service_content.replace('@@RESPONSE_GET_BUFFER_MEMBERS@@', response_get_buffer_member_string)
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

def find_topic_directories(script_directory, search_directories):
    """
    Search for all subdirectories in <script_directory> containing 'CMakeLists.txt'.
    Return a list of these directories.
    The function will not search further into subdirectories once a 'CMakeLists.txt' file is found.

    :param script_directory: The root directory where the search starts.
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

def find_project_directories(script_directory, search_directories, install_dir, packages_to_ignore=[]):
    """
    Search for all subdirectories in <script_directory> containing 'CMakeLists.txt'.
    Return a list of these directories.
    The function will not search further into subdirectories once a 'CMakeLists.txt' file is found.

    :param script_directory: The root directory where the search starts.
    :param search_directories: A list of directories to search (e.g., ['src', 'messages']).
    """

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

def find_interface_files(script_directory, search_directories, interface_types, packages_to_ignore=None):
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

            for dir in dirs:
                if (search_path / dir / 'include').is_dir():
                    shutil.copytree(search_path / dir / 'include',
                                    generated_dest_dir / dir / 'include', dirs_exist_ok=True)

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


def update_cmake_file(script_directory, project_directories, cmake_dir):
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

def create_action_file(action_file, script_directory, project_directory):
    """
    Create a message file based on the template, replacing '@@MESSAGE_NAME@@' with the message file name.
    The file is saved in <script_directory>/include/<project_directory>/msg.
    """
    template_path = os.path.join(script_directory, 'templates', 'ActionTemplate.hpp')

    # Extract the project name from the project directory path
    project_name = os.path.basename(project_directory)

    # Determine the target directory in include/<project_name>/msg
    include_project_msg_dir = os.path.join(script_directory, 'generated', 'include', project_name, 'action')
    destination_file = os.path.join(script_directory, 'install', 'messages', project_name, 'action', '')
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
        print(f"📂 Reading action file: {action_path}")
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


def create_message_file(msg_file, script_directory, project_directory):
    """
    Create a message file based on the template, replacing '@@MESSAGE_NAME@@' with the message file name.
    The file is saved in <script_directory>/include/<project_directory>/msg.
    """
    template_path = os.path.join(script_directory, 'templates', 'MessageTemplate.hpp')

    # Extract the project name from the project directory path
    project_name = os.path.basename(project_directory)

    # Determine the target directory in include/<project_name>/msg
    include_project_msg_dir = os.path.join(script_directory, 'generated', 'include', project_name, 'msg')
    destination_file = os.path.join(script_directory, 'install', 'messages', project_name, 'msg', '')
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

    for bm in buffer_members:
        set_buffer_member_string += f"::raisin::setBuffer(buffer, {bm});\n"

    for bm in buffer_members:
        get_buffer_member_string += f"temp = ::raisin::getBuffer(temp, {bm});\n"

    message_content = message_content.replace('@@SET_BUFFER_MEMBERS@@', set_buffer_member_string)
    modified_set_buffer_member_string = "\n".join("buffer = " + line for line in set_buffer_member_string.splitlines())
    message_content = message_content.replace('@@SET_BUFFER_MEMBERS2@@', modified_set_buffer_member_string)

    message_content = message_content.replace('@@GET_BUFFER_MEMBERS@@', get_buffer_member_string)

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

def copy_installers(script_directory, src_dir, install_dir) -> int:
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
        print(f"📂 Copied {src_installer}  ➜  {dst_subdir}")

    return copied


def deploy_install_packages(script_directory: str):
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
    os_type = platform.freedesktop_os_release()['ID']
    architecture = platform.machine()
    os_version = platform.freedesktop_os_release()['VERSION_ID']

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

            # Copy contents, merging files from different build_types
            shutil.copytree(source_dir, final_dest_dir, dirs_exist_ok=True)

            if (p / 'generated').is_dir():
                shutil.copytree(p / 'generated', generated_dest_dir, dirs_exist_ok=True)

        if deployed_targets:
            print(f"\n✅ Successfully deployed {len(deployed_targets)} target(s).")

    except Exception as e:
        print(f"❌ An error occurred during deployment: {e}")

def setup(script_directory, package_name = "", build_type = "", build_dir = ""):
    """
    setup function to find project directories, msg, and srv files and generate message and service files.
    """
    os_type = platform.freedesktop_os_release()['ID']
    architecture = platform.machine()
    os_version = platform.freedesktop_os_release()['VERSION_ID']

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

    action_files = find_interface_files(script_directory, [src_dir], ['action'], packages_to_ignore)[0]

    project_directories = find_project_directories(script_directory, [src_dir], install_dir, packages_to_ignore)

    # Handle .action files
    for action_file in action_files:
        create_action_file(action_file, script_directory, Path(action_file).parent.parent)

    msg_files, srv_files = find_interface_files(script_directory, [src_dir, 'temp'], ['msg', 'srv'], packages_to_ignore)

    # Handle .msg files
    for msg_file in msg_files:
        create_message_file(msg_file, script_directory, Path(msg_file).parent.parent)

    # Handle .srv files
    for srv_file in srv_files:
        create_service_file(srv_file, script_directory, Path(srv_file).parent.parent)


    # script_dir = os.path.dirname(os.path.abspath(__file__))
    # install_dir = os.path.join(script_dir, "install")
    # generated_dir = os.path.join(script_dir, "generated")
    #
    # os.makedirs(install_dir, exist_ok=True)
    #
    # for project_name in os.listdir(messages_dir):
    #     dest_dir = os.path.join(install_dir, "include", project_name)
    #     generated_dest_dir = os.path.join(generated_dir, "include", project_name)
    #
    #     if os.path.isdir(src_dir):  # Ensure only directories are copied
    #         shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True)
    #         print(f"📂 Copied: {src_dir} -> {dest_dir}")
    #         shutil.copytree(src_dir, generated_dest_dir, dirs_exist_ok=True)

    # Update the CMakeLists.txt based on the template
    update_cmake_file(script_directory, project_directories, build_dir)

    copy_installers(script_directory, src_dir, install_dir)

    if package_name == "": # this means we are not in the release mode
        copy_resource(install_dir)

    shutil.copy(os.path.join(script_directory, 'templates', 'raisin_serialization_base.hpp'), os.path.join(script_directory, 'generated/include'))

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

    shutil.copy2(Path(script_directory)/'templates/install_dependencies.sh', Path(script_directory)/'install/install_dependencies.sh')

    # install generated files
    shutil.copytree(Path(script_directory) / "generated",
                    Path(script_directory) / install_dir / 'generated', dirs_exist_ok=True)

    deploy_install_packages(script_directory)

def release(script_directory, target, build_type):
    """
    Checks for a target subdirectory in '<script_directory>/src',
    reads its 'release.yaml', and then builds the project using all available CPU cores.

    Args:
        script_directory (str): The absolute path to the script's root directory.
        target (str): The name of the target subdirectory to check for.
    """
    target_dir = os.path.join(script_directory, 'src', target)

    os_type = platform.freedesktop_os_release()['ID']
    architecture = platform.machine()
    os_version = platform.freedesktop_os_release()['VERSION_ID']

    install_dir = f"{script_directory}/release/install/{target}/{os_type}/{os_version}/{architecture}/{build_type}"

    # Check if target directory exists
    if not os.path.isdir(target_dir):
        print(f"❌ Error: Target '{target}' not found in '{os.path.join(script_directory, 'src')}'.")
        return

    release_file_path = os.path.join(target_dir, 'release.yaml')
    repository_file_path = os.path.join(script_directory, 'repositories.yaml')

    # Check if release.yaml exists
    if not os.path.isfile(release_file_path):
        print(f"❌ Error: 'release.yaml' not found in '{target_dir}'.")
        return

    print(f"✅ Found release file for '{target}'.")

    try:
        with open(release_file_path, 'r') as file:
            with open(repository_file_path, 'r') as repository_file:
                details = yaml.safe_load(file)
                repositories = yaml.safe_load(repository_file)

                # --- BUILD STEPS NOW INLINED ---
                print(f"\n--- Setting up build for '{target}' ---")
                build_dir = Path(script_directory) / "release" / "build" / target
                delete_directory(build_dir)  # Delete the existing build directory
                setup(script_directory, package_name = target, build_type=build_type, build_dir = str(build_dir))
                os.makedirs(build_dir / "build", exist_ok=True)

                # 1. Run CMake
                print("⚙️  Running CMake...")
                cmake_command = ["cmake",
                                 "../../../..",
                                 "-G Ninja",
                                 f"-DCMAKE_INSTALL_PREFIX={install_dir}",
                                 f"-DCMAKE_BUILD_TYPE={build_type}",
                                 "-DRAISIN_RELEASE_BUILD=ON"]
                try:
                    subprocess.run(
                        cmake_command,
                        cwd=build_dir / "build",
                        check=True,
                        capture_output=True,
                        text=True
                    )
                    print("✅ CMake configuration successful.")
                except FileNotFoundError:
                    print("❌ Error: 'cmake' command not found. Is CMake installed and in your PATH?")
                    return
                except subprocess.CalledProcessError as e:
                    print(f"❌ CMake failed with exit code {e.returncode}:\n{e.stderr}")
                    return

                # 2. Build with Ninja, using all available CPU cores
                print("🛠️  Building with Ninja...")

                # Get the number of CPU cores available on the system
                core_count = int(os.cpu_count() / 2) or 4 # Fallback to 4 if count is undetermined
                print(f"🔩 Using {core_count} cores for the build.")

                # Dynamically set the job count '-j' for Ninja
                build_command = ["ninja", "install", f"-j{core_count}"]

                try:
                    subprocess.run(
                        build_command,
                        cwd=build_dir / "build",
                        check=True,
                        capture_output=True,
                        text=True
                    )
                    print(f"✅ Build for '{target}' complete!")
                except FileNotFoundError:
                    print("❌ Error: 'ninja' command not found. Is Ninja installed and in your PATH?")
                    return
                except subprocess.CalledProcessError as e:
                    print(f"❌ Ninja build failed with exit code {e.returncode}:\n{e.stderr}")
                    return

                shutil.copy(Path(script_directory) / 'src' / target / 'release.yaml', Path(install_dir) / 'release.yaml')

                # --- NEW: COMPRESS THE INSTALLED DIRECTORY ---
                print("\n--- Creating Release Archive ---")
                # 1. Get required information for the filename
                version = details.get('version', '0.0.0')

                # 2. Define source directory and archive name
                archive_name_base = f"{target}-{os_type}-{os_version}-{architecture}-{build_type}-v{version}"
                archive_output_path = os.path.join(install_dir, archive_name_base)

                try:
                    print(f"📦 Compressing '{install_dir}'...")

                    # 3. Create the zip archive
                    try:
                        release_dir = Path(script_directory) / 'release'
                        archive_file = release_dir / (archive_name_base + '.zip')

                        subprocess.run(
                            ['zip', '-r', str(archive_file), '.'],
                            cwd=install_dir,
                            check=True,      # Raises an exception if zip fails
                            capture_output=True # Hides the command's output unless there's an error
                        )

                        print(f"✅ Successfully created archive: {archive_file}")

                    except FileNotFoundError:
                        print("❌ ERROR: The 'zip' command is not installed or not in your PATH.")
                    except subprocess.CalledProcessError as e:
                        print(f"❌ ERROR: Archiving failed with exit code {e.returncode}.")
                        print(e.stderr.decode())

                    print(f"✅ Successfully created release archive:\n   {archive_file}")

                except KeyError:
                    print("❌ Error: Could not find 'release: version:' key path in release.yaml.")
                except FileNotFoundError:
                    print(f"❌ Error: Install directory not found at '{install_dir}'. Cannot create archive.")
                except Exception as e:
                    print(f"❌ An unexpected error occurred during archiving: {e}")

                # --- NEW: UPLOAD TO GITHUB RELEASE ---
                secrets_path = os.path.join(script_directory, 'secrets.yaml')
                if not os.path.isfile(secrets_path):
                    print("❌ Error: 'secrets.yaml' not found. Cannot authenticate for GitHub upload.")
                    return
                with open(secrets_path, 'r') as secrets_file:
                    secrets = yaml.safe_load(secrets_file)

                try:
                    print("\n--- Uploading to GitHub Release ---")
                    try:
                        # 1. Get GitHub info from YAML
                        release_info = repositories.get(target)
                        if not release_info:
                            print(f"ℹ️ {target} in 'repositories.yaml' not found in YAML. Skipping GitHub release.")
                            return

                        repo_url = release_info.get('url')
                        if not repo_url:
                            print("ℹ️ 'release.url' not found in YAML. Skipping GitHub release.")
                            return

                        # 2. Get token from secrets and prepare environment
                        path = urlparse(repo_url).path
                        token = secrets.get("gh_tokens").get(path.split(':')[1].split('/')[0])

                        if not token:
                            print(f"❌ Error: Token for '{repo_url}' not found in secrets.yaml.")
                            return
                        auth_env = os.environ.copy()
                        auth_env["GH_TOKEN"] = token

                        # 3. Parse repo slug and define release details
                        match = re.search(r'git@github\.com:(.*)\.git', repo_url)
                        repo_slug = match.group(1) if match else None
                        if not repo_slug:
                            print(f"❌ Error: Could not parse repository from URL: {repo_url}")
                            return
                        tag_name = f"v{version}"

                        # 4. Try to upload to an existing release first
                        print(f"🚀 Checking for existing release '{tag_name}' in '{repo_slug}'...")
                        try:
                            gh_upload_cmd = [
                                "gh", "release", "upload", tag_name, archive_file,
                                "--repo", repo_slug
                            ]
                            subprocess.run(gh_upload_cmd, check=True, capture_output=True, text=True, env=auth_env)
                            print(f"✅ Successfully uploaded asset to existing release '{tag_name}'.")
                        # Capture the exception object to inspect its output
                        except subprocess.CalledProcessError as e:
                            # Now, try to create the release
                            print(f"ℹ️ Assuming release '{tag_name}' does not exist. Creating a new one...")
                            gh_create_cmd = [
                                "gh", "release", "create", tag_name, archive_file,
                                "--repo", repo_slug,
                                "--title", f"{tag_name}",
                                "--notes", f"Automated release of version {version}.",
                                "--draft=false"
                            ]
                            subprocess.run(gh_create_cmd, check=True, capture_output=True, text=True, env=auth_env)
                            print(f"✅ Successfully created new release and uploaded asset.")
                    except Exception as e:
                        print(f"❌ An error occurred during GitHub upload: {e}")

                except Exception as e:
                    print(f"🔥 An unexpected top-level error occurred: {e}")

    except yaml.YAMLError as e:
        print(f"🔥 Error parsing YAML file: {e}")
    except Exception as e:
        print(f"🔥 An unexpected error occurred: {e}")

def install(script_directory, targets, build_type):
    """
    Downloads and installs packages and their dependencies recursively. It automatically
    processes all packages in the 'src' directory, then prioritizes existing precompiled
    versions, then local sources, before downloading from GitHub.

    Args:
        script_directory (str): The root directory where config files are located
                                and where packages will be installed.
        targets (list): A list of strings, each specifying a package to install,
                        e.g., ["raisin", "my-plugin>=1.2<2.0"].
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

    # ## 2. System Information (Omitted for brevity)
    os_type = platform.freedesktop_os_release()['ID']
    architecture = platform.machine()
    os_version = platform.freedesktop_os_release()['VERSION_ID']

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
                specifiers_list = list(filter(None, re.split(r'\s*(?=[<>=!~])', spec_str)))
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
    print("="*50)
    print(f"Usage: python {script_name} <command> [options]\n")

    print("Core Commands:")
    print("  setup [target ...]")
    print("    🛠️  Generates message headers and configures the main CMakeLists.txt")
    print("        for a development build. If specific targets are provided, it")
    print("        configures only those targets and their dependencies. If no")
    print("        targets are given, it configures all found projects.\n")

    print("  build <release|debug> [install]")
    print("    ⚙️  Performs a local build in a `cmake-build-*` directory.")
    print("        You must specify the build type: `release` or `debug`.")
    print("        Optionally add `install` to install the build to 'install' directory.\n")

    print("  release <target ...> [build_type]")
    print("    📦 Creates and archives a distributable package for one or more")
    print("        targets. Packages are placed in the `release/` directory")
    print("        and automatically uploaded to GitHub Releases if configured.")
    print("        - `build_type` can be `release` (default) or `debug`.\n")

    print("  install [package_spec ...] [build_type]")
    print("    🚀 Downloads and installs pre-compiled packages and their")
    print("        dependencies. If no packages are specified, it scans `src/`.")
    print("        - A `package_spec` can include a version (e.g., `my_pkg>=1.2.3`).")
    print("        - `build_type` can be `release` (default) or `debug`.\n")

    print("  help, -h, --help")
    print("    ❓ Displays this help message.")
    print("-" * 50)

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

def process_repo(repo_path, pull_mode=False, origin="origin"):
    """
    Processes a single git repository.
    - If pull_mode is False, it checks the status.
    - If pull_mode is True, it pulls and returns a clean summary.
    """
    is_current_dir = repo_path == os.getcwd()
    dir_name = f"{os.path.basename(repo_path)}{' (current)' if is_current_dir else ''}"

    if pull_mode:
        print(f"🌀 Pulling for {dir_name}...")
        branch = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_path)

        # Default to failure unless a success condition is met
        pull_status = "Failed"
        pull_message = "An unknown error occurred."

        if "Error:" in branch:
            pull_message = "Could not determine current branch."
        else:
            pull_result = run_command(["git", "pull", origin, branch], repo_path)

            # --- PARSE PULL RESULT FOR CLEAN OUTPUT ---
            if "Error:" in pull_result:
                if "would be overwritten" in pull_result:
                    pull_message = "Local changes would be overwritten."
                elif "fix conflicts" in pull_result:
                    pull_message = "Merge conflict detected."
                elif "couldn't find remote ref" in pull_result:
                    pull_message = f"Remote branch '{branch}' not found."
                else:
                    pull_message = "See error details above." # Generic error
            else: # Success cases
                pull_status = "Success"
                if "Already up to date" in pull_result:
                    pull_message = "Already up to date."
                elif "Fast-forward" in pull_result:
                    pull_message = "Updated successfully (fast-forward)."
                else:
                    pull_message = "Pull successful (merge)."

        return {"name": dir_name, "status": pull_status, "message": pull_message}
    else:
        # Status check logic (unchanged)
        run_command(["git", "fetch", "--quiet"], repo_path)
        branch = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_path)
        changes = run_command(["git", "diff", "--shortstat", "HEAD"], repo_path)
        lines_to_commit = "No changes"
        if changes:
            lines_to_commit = changes.replace(" files changed", "f").replace(" file changed", "f").replace(" insertions(+)", "+").replace(" deletions(-)", "-")

        local = run_command(["git", "rev-parse", "HEAD"], repo_path)
        remote = run_command(["git", "rev-parse", f"{origin}/{branch}"], repo_path)
        base = run_command(["git", "merge-base", "HEAD", f"{origin}/{branch}"], repo_path)

        sync_status = ""
        if "Error:" in local or "Error:" in remote:
            sync_status = f"⚠️ No remote for '{branch}'"
        elif local == remote:
            sync_status = "✅ Up to date"
        elif local == base:
            sync_status = "⬇️ Behind"
        elif remote == base:
            sync_status = "⬆️ Ahead"
        else:
            sync_status = "🔱 Diverged"

        return {"name": dir_name, "branch": branch, "changes": lines_to_commit, "status": sync_status}


def manage_git_repos(pull_mode, origin = "origin"):
    """
    Manages Git repositories in the current directory and './src'.
    - Default: Checks status.
    - With '--pull' argument: Pulls and provides a clean summary.
    """

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
        lambda path: process_repo(path, pull_mode=pull_mode), repo_paths
    ))
    all_results.sort(key=lambda x: x['name'])

    if pull_mode:
        print("\n--- Pull Summary ---")
        max_name = max(len(d['name']) for d in all_results)
        for res in all_results:
            icon = "✅" if res['status'] == 'Success' else "❌"
            print(f"{icon} {res['name']:<{max_name}}  ->  {res['message']}")
    else:
        # Original table printing logic
        max_name = max(len(d['name']) for d in all_results)
        max_branch = max(len(d['branch']) for d in all_results)
        max_changes = max(len(d['changes']) for d in all_results)

        header = (f"{'REPOSITORY':<{max_name}} | {'BRANCH':<{max_branch}} | {'PENDING CHANGES':<{max_changes}} | STATUS")
        print(header)
        print('-' * len(header))
        for repo in all_results:
            print(f"{repo['name']:<{max_name}} | {repo['branch']:<{max_branch}} | {repo['changes']:<{max_changes}} | {repo['status']}")


if __name__ == '__main__':
    script_directory = os.path.dirname(os.path.realpath(__file__))
    delete_directory(os.path.join(script_directory, 'temp'))

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

        setup(script_directory)

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
                    release(script_directory, target, build_type)
                print("All targets released.")

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
        install(script_directory, targets, build_type)

    elif len(sys.argv) >= 3 and sys.argv[1] == 'git':
        if sys.argv[2] == 'status':
            manage_git_repos(pull_mode=False)
        if sys.argv[2] == 'pull':
            if len(sys.argv) >= 4:
                manage_git_repos(pull_mode=True, origin=sys.argv[2])
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

            core_count = int(os.cpu_count() / 2) or 4
            print(f"🛠️ Using {core_count} cores for the build.")

            try:
                result = subprocess.run(
                    cmake_command,
                    cwd=build_dir,
                    check=True,
                    capture_output=True,
                    text=True
                )
                print("✅ CMake configured successfully!")
                print(result.stdout)


            except subprocess.CalledProcessError as e:
                print(f"❌ CMake failed with exit code {e.returncode}:")
                print(e.stderr)

            print(f"🛠️ Running ninja build.")

            # Dynamically set the job count '-j' for Ninja
            build_command = ["ninja", f"-j{core_count}"]

            if to_install:
                build_command.append("install")

            try:
                subprocess.run(
                    build_command,
                    cwd=build_dir,
                    check=True,
                    capture_output=True,
                    text=True
                )

            except FileNotFoundError:
                print("❌ Error: 'ninja' command not found. Is Ninja installed and in your PATH?")
                exit(1)

            except subprocess.CalledProcessError as e:
                print(f"❌ Ninja build failed with exit code {e.returncode}:\n{e.stderr}")
                exit(1)

        print("🎉🎉🎉 Building process finished successfully.")
