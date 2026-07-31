@echo off
setlocal

echo Building VeloLeads Executable (Single File Mode)...
echo Cleaning old builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo Checking Python environment...
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    set "PYINSTALLER_EXE=.venv\Scripts\pyinstaller.exe"
) else (
    set "PYTHON_EXE=python"
    set "PYINSTALLER_EXE=pyinstaller"
)

echo Closing any previous VeloLeads instance if it is running...
taskkill /F /IM "VeloLeads.exe" 2>nul

echo Waiting for the process to release the EXE file...
timeout /t 2 /nobreak >nul

if exist "dist\VeloLeads.exe" (
    echo Deleting stale EXE...
    del /f /q "dist\VeloLeads.exe" 2>nul
)

if exist dist (
    echo Removing stale dist folder...
    rmdir /s /q dist
)

mkdir dist

echo Generating User Guide PDF...
%PYTHON_EXE% generate_pdf.py
if errorlevel 1 (
    echo.
    echo PDF Generation failed. Please check generate_pdf.py.
    exit /b 1
)

echo Running PyInstaller...
%PYINSTALLER_EXE% --noconfirm --clean --onefile --windowed --icon="icon.ico" --add-data "icon.ico;." --name "VeloLeads" "ui.py"

if errorlevel 1 (
    echo.
    echo PyInstaller failed. Please check the output above.
    exit /b 1
)

echo Packaging Windows release ZIP...
if exist "dist\VeloLeads-Windows-EXE.zip" (
    del /f /q "dist\VeloLeads-Windows-EXE.zip" 2>nul
)
powershell -Command "Compress-Archive -Path 'dist\VeloLeads.exe', 'VeloLeads_User_Guide.pdf' -DestinationPath 'dist\VeloLeads-Windows-EXE.zip' -Force"

if errorlevel 1 (
    echo.
    echo Packaging release ZIP failed.
    exit /b 1
)

echo.
echo ========================================================
echo Build Complete!
echo You can find the standalone application and guide zip in 'dist':
echo dist\VeloLeads-Windows-EXE.zip (Contains VeloLeads.exe and VeloLeads_User_Guide.pdf)
echo ========================================================
pause

