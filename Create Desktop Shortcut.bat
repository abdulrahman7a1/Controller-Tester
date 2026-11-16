@echo off
title DualSense Tester - setup
cd /d "%~dp0"
echo.
echo  DualSense Tester - making the desktop app
echo  ==========================================
echo.
echo  [1/3] Installing pygame-ce, PyInstaller and the tray helper...
python -m pip install --upgrade pygame-ce pyinstaller pystray pillow
if errorlevel 1 goto nopython

echo.
echo  [2/3] Building "DualSense Tester.exe" (takes about a minute)...
python -m PyInstaller --noconfirm --clean --windowed --name "DualSense Tester" --icon "dualsense.ico" --add-data "dualsense.png;." --hidden-import pystray._win32 controller_tester.py
if not exist "dist\DualSense Tester\DualSense Tester.exe" goto fallback

set "SC_TARGET=%~dp0dist\DualSense Tester\DualSense Tester.exe"
set "SC_ARGS="
set "SC_DIR=%~dp0dist\DualSense Tester"
goto makeshortcut

:fallback
echo.
echo  Building the .exe didn't work, so the shortcut will run the script directly instead.
for /f "delims=" %%P in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set "SC_TARGET=%%P"
set "SC_ARGS="%~dp0controller_tester.py""
set "SC_DIR=%~dp0"

:makeshortcut
echo.
echo  [3/3] Creating the desktop shortcut...
set "SC_ICON=%~dp0dualsense.ico"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'DualSense Tester.lnk')); $s.TargetPath=$env:SC_TARGET; $s.Arguments=$env:SC_ARGS; $s.WorkingDirectory=$env:SC_DIR; $s.IconLocation=$env:SC_ICON; $s.Description='DualSense controller tester'; $s.Save()"
if errorlevel 1 goto failed
echo.
echo  Done! Close any open DualSense Tester first (right-click its tray icon, Quit),
echo  then double-click "DualSense Tester" on your desktop.
echo.
pause
exit /b 0

:nopython
echo.
echo  Couldn't run Python / pip. Make sure "python" works in Command Prompt, then try again.
pause
exit /b 1

:failed
echo.
echo  Couldn't create the shortcut. Send a screenshot of this window to Claude.
pause
exit /b 1
