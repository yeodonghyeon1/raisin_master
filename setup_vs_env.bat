@echo off

REM Find vswhere.exe
set "vswhere=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%vswhere%" (
    echo Cannot find vswhere.exe.
    pause
    exit /b 1
)

REM Find the latest VS installation path
for /f "usebackq tokens=*" %%i in (`"%vswhere%" -latest -property installationPath`) do (
    set "VS_PATH=%%i"
)

if not defined VS_PATH (
    echo Could not find a Visual Studio installation.
    pause
    exit /b 1
)

REM Set the path to the environment script
set "VCVARS_SCRIPT=%VS_PATH%\VC\Auxiliary\Build\vcvarsall.bat"

REM Launch a new command prompt with the environment loaded for x64
echo Loading Visual Studio x64 environment...
cmd.exe /k "%VCVARS_SCRIPT%" x64