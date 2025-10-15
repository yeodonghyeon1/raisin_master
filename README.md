# RAISIN: Raion System Installer

RAISIN is a Python-based build-system wrapper designed to simplify dependency management and project compilation for CMake-based projects at Raion Robotics. It automates the process of fetching dependencies, configuring the build environment, and compiling the source code.

---

## 📜 License and Disclaimer

This software is proprietary and is licensed under the terms detailed in the `LICENSE` file. **Its use is exclusively permitted for products and projects developed by or for Raion Robotics Inc.**

---

## ✅ Prerequisites

Before you begin, ensure your system meets the following requirements.

### Supported Operating Systems
* **Windows**: 10 / 11
* **Linux**: Ubuntu 22.04 / 24.04

### Dependencies

#### For Linux
The provided shell script automates the entire dependency installation process. Simply run:
```bash
bash install_dependencies.sh
```

#### For Windows
You will need to manually install the following software. Please ensure that the executables for **Git**, **Git CLI**, and **Ninja** are available in your system's `Path` environment variable.

* [Python](https://www.python.org/downloads/) (version 3.8 or newer)
* [Git](https://git-scm.com/download/win)
* [Git CLI](https://github.com/cli/cli/releases)
* [Ninja](https://github.com/ninja-build/ninja/releases)
* [Visual Studio 2022](https://visualstudio.microsoft.com/vs/) (with the "Desktop development with C++" workload)

### Project Initialization

Once the above dependencies are installed, complete the following steps in your terminal:

1.  **Initialize Git Submodules:** (Only for Windows) This project uses `vcpkg` as a git submodule for C++ package management in Windows.
    ```bash
    git submodule update --init
    ```

2.  **Install Required Python Packages:**
    ```bash
    pip3 install PyYAML packaging requests
    ```

---

## 🚀 Getting Started

Follow these steps to configure and build your project.

### 1. Project Configuration

Create your local configuration file by copying the provided example.
```bash
cp configuration_setting_example.yaml configuration_setting.yaml
```
Next, open **`configuration_setting.yaml`** and edit the following fields:
* **`gh_token`**: Set this to the GitHub Personal Access Token provided to you by Raion Robotics.
* **`target_type`**: Set to `devel` for development builds.
* **`raisin_ignore`**: (Optional) Add the names of any packages you wish to exclude from the dependency resolution process.

### 2. Add Source Packages

Create a directory named `src` in the root of the repository. Clone any source code packages you are developing or contributing to inside this `src` directory.
```bash
mkdir src
cd src
git clone <your-package-repository>
```

### 3. Install Dependencies

Run the `install` command to let RAISIN resolve and install all necessary dependencies for the packages located in the `src` directory.
```bash
python3 raisin.py install
```

### 4. Generate Build Files

Run the script without any arguments to configure the CMake environment and generate the native build files (e.g., a Visual Studio solution or Makefiles).
```bash
python3 raisin.py
```

### 5. Build the Project

You can now compile the project. The recommended method is to use the RAISIN build command, which builds the project and places the output in the `install/` directory.

```bash
# Build the 'debug' configuration and then install it
python3 raisin.py build debug install
```
Alternatively, advanced users can use standard CMake commands (``cmake ..``) in the `build/` directory.
For Windows users, use provided presets (``debug`` and ``release``).

---

## 📚 Documentation

For more detailed information and API references, please visit our official documentation:

**[https://raionrobotics.com/documentation](https://raionrobotics.com/documentation)**