@echo off
echo ==========================================
echo       Resetting ADB Connection
echo ==========================================
echo.
echo [1/3] Killing ADB server...
adb kill-server

timeout /t 2 /nobreak >nul

echo.
echo [2/3] Starting ADB server and connecting...
adb start-server
adb connect 127.0.0.1:5555

echo.
echo [3/3] Device List:
echo ------------------------------------------
adb devices
echo ------------------------------------------
echo.
echo If you see "127.0.0.1:5555 device", connection is successful!
echo.
pause
