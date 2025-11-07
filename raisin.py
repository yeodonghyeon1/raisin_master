import os
import glob
import sys
from pathlib import Path
import yaml
from commands import globals as g
from commands.build import build_command
from commands.git_commands import (
    git_status_command,
    git_pull_command,
    git_setup_remotes_command,
)
from commands.help import print_help
from commands.index import index_release_command, index_local_command
from commands.install import install_command
from commands.release import release
from commands.setup import setup
from commands.utils import get_os_info, delete_directory

try:
    from packaging.requirements import Requirement
    from packaging.version import Version, InvalidVersion
    from packaging.specifiers import InvalidSpecifier
except ImportError:
    print("Error: 'packaging' library not found.")
    print("Please install it running: pip install packaging")
    exit(1)

if __name__ == "__main__":
    script_directory = Path(os.path.dirname(os.path.realpath(__file__))).as_posix()
    (
        os_type,
        architecture,
        os_version,
        visual_studio_path,
        ninja_path,
        developer_env,
    ) = get_os_info()

    # Initialize commands.globals for modular commands
    g.init_globals(
        script_directory=script_directory,
        os_type=os_type,
        architecture=architecture,
        os_version=os_version,
        ninja_path=ninja_path,
        visual_studio_path=visual_studio_path,
        developer_env=developer_env,
        build_pattern=[],
        vcpkg_dependencies=set(),
        always_yes=False,
    )

    delete_directory(os.path.join(script_directory, "temp"))

    # Display help if no arguments are given or if help is explicitly requested
    if any(arg in sys.argv for arg in ["help", "-h", "--help"]):
        print_help()
        exit(0)

    always_yes = "--yes" in sys.argv
    if always_yes:
        sys.argv.remove("--yes")
        g.always_yes = True  # Update commands.globals

    if len(sys.argv) == 1 or sys.argv[1] == "setup" or sys.argv[1] == "build":
        targets = sys.argv[2:]

        # 1. Find and parse all YAML files to create a master dictionary
        if (
            len(sys.argv) > 3
            and (Path(script_directory) / "src" / sys.argv[2]).exists()
        ):
            g.build_pattern = [
                name
                for name in os.listdir(Path(script_directory) / "src" / sys.argv[2])
                if os.path.isdir(
                    os.path.join(Path(script_directory) / "src" / sys.argv[2], name)
                )
            ]
        else:
            all_build_maps = {}
            yaml_search_path = os.path.join(
                script_directory, "src", "**", "RAISIN_BUILD_TARGETS.yaml"
            )

            for filepath in glob.glob(yaml_search_path, recursive=True):
                with open(filepath, "r") as f:
                    try:
                        # Load the YAML content and merge it into the master dictionary
                        yaml_content = yaml.safe_load(f)
                        if yaml_content:
                            all_build_maps.update(yaml_content)
                    except yaml.YAMLError as e:
                        print(
                            f"Warning: Could not parse YAML file {filepath}. Error: {e}"
                        )

            # 2. Collect build patterns based on the input targets
            found_patterns = []
            for target in targets:
                # Use .get() to find patterns for the target; returns an empty list if not found
                patterns_for_target = all_build_maps.get(target, [])
                found_patterns.extend(patterns_for_target)

            # 3. Update the global build_pattern variable
            g.build_pattern = found_patterns

        if not g.build_pattern:
            print("🛠️ building all patterns")
        else:
            print(f"🛠️ building the following targets: {g.build_pattern}")

        setup()

    elif sys.argv[1] == "release":
        # Check if any arguments are provided after 'release'
        if len(sys.argv) < 3:
            print("❌ Error: Please specify at least one target to release.")
        else:
            # Check if the last argument is a specific build type
            if sys.argv[-1].lower() in ("release", "debug"):
                build_type = sys.argv[-1].lower()
                # All arguments between 'release' and the final build type are targets
                targets = sys.argv[2:-1]
            else:
                # Otherwise, default the build type to 'release'
                build_type = "release"
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

    elif sys.argv[1] == "index":
        if len(sys.argv) >= 3 and sys.argv[2] == "release":
            # Case 1: Package name is provided, list its versions
            if len(sys.argv) == 4:
                package_name = sys.argv[3]
                index_release_command(package_name)
            # Case 2: No package name, list all available packages
            elif len(sys.argv) == 3:
                index_release_command()
            else:
                print(
                    "❌ Error: Invalid 'index versions' command. Provide zero or one package name."
                )
        elif len(sys.argv) >= 3 and sys.argv[2] == "local":
            index_local_command()
        else:
            print(
                "❌ Error: Invalid 'index' command. Use: index release or index 'local"
            )

    elif sys.argv[1] == "install":
        # Set default build type
        build_type = "release"

        # Get all potential targets (all arguments after 'install')
        targets = sys.argv[2:]

        # Check if the last argument specifies the build type
        if targets and targets[-1] in ["release", "debug"]:
            # If it does, set the build type
            build_type = targets[-1]
            # And remove it from the list of targets
            targets = targets[:-1]

        # Call the 'install' command with the parsed arguments
        install_command(targets, build_type)

    elif len(sys.argv) >= 3 and sys.argv[1] == "git":
        # Git commands using modular functions

        if sys.argv[2] == "status":
            git_status_command()
        if sys.argv[2] == "pull":
            if len(sys.argv) >= 4:
                git_pull_command(origin=sys.argv[3])
            else:
                git_pull_command()
        elif sys.argv[2] == "setup":
            if len(sys.argv) < 4:
                print("❌ Error: Please provide at least one remote specification.")
                print(
                    "   Usage: python raisin.py git setup <name1:user1> <name2:user2> ..."
                )
            else:
                remote_specs = sys.argv[3:]
                git_setup_remotes_command(remote_specs)

    else:
        print("❌ Error: No command-line arguments were provided.")

    if len(sys.argv) >= 2 and sys.argv[1] == "build":
        build_types = sys.argv[2:]
        to_install = "install" in build_types
        build_types = [bt for bt in build_types if bt != "install"]

        build_command(build_types, to_install)
