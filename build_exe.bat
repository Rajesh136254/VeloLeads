@echo off
setlocal

echo Building VeloLeads Executable (Single File Mode)...
echo Cleaning old builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

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

echo Running PyInstaller...
pyinstaller --noconfirm --clean --onefile --windowed --name "VeloLeads" "ui.py"

if errorlevel 1 (
    echo.
    echo PyInstaller failed. Please check the output above.
    exit /b 1
)

echo.
echo ========================================================
echo Build Complete!
echo You can find the standalone application in the 'dist' folder:
echo dist\VeloLeads.exe
echo ========================================================
pause
