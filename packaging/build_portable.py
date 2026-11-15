"""Builds the direct-download ShrinkDrop zip (for Gumroad / Lemon Squeezy).

    build\\venv\\Scripts\\python packaging\\build_portable.py

Output: build\\ShrinkDrop-Windows.zip containing
    Install ShrinkDrop.cmd     copies the app to %LOCALAPPDATA%\\Programs\\ShrinkDrop and starts it
    Uninstall ShrinkDrop.cmd   removes the right-click menu, shortcuts and the program folder
    READ ME FIRST.txt
    ShrinkDrop\\               self-contained app (bundled python.org Python, PSF-signed pythonw.exe)
"""
import compileall
import os
import shutil
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_msix as bm  # noqa: E402

ROOT = bm.ROOT
STAGE = os.path.join(os.path.expanduser("~"), "ShrinkDrop-portable")
OUT = os.path.join(ROOT, "build", "ShrinkDrop-Windows.zip")
VERSION = "1.0.0"

INSTALL_CMD = r"""@echo off
setlocal
title Install ShrinkDrop
set "DEST=%LOCALAPPDATA%\Programs\ShrinkDrop"
echo.
echo  Installing ShrinkDrop to %DEST% ...
robocopy "%~dp0ShrinkDrop" "%DEST%" /MIR /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo  Copy failed. Close ShrinkDrop and run this again.
  pause
  exit /b 1
)
start "" "%DEST%\python\pythonw.exe" "%DEST%\app\main.py"
echo.
echo  Done! ShrinkDrop is on your Desktop and in the Start menu.
echo  Tip: right-click any photo or video and choose "Shrink with ShrinkDrop".
echo.
timeout /t 8 >nul
"""

UNINSTALL_CMD = r"""@echo off
setlocal
title Uninstall ShrinkDrop
set "DEST=%LOCALAPPDATA%\Programs\ShrinkDrop"
taskkill /f /fi "WINDOWTITLE eq ShrinkDrop" >nul 2>&1
if exist "%DEST%\python\python.exe" "%DEST%\python\python.exe" "%DEST%\app\main.py" --uninstall --quiet
timeout /t 1 >nul 2>&1
rd /s /q "%DEST%" 2>nul
rd /s /q "%APPDATA%\ShrinkDrop" 2>nul
echo ShrinkDrop has been removed. Your photos and videos were not touched.
timeout /t 6 >nul
"""

README = f"""ShrinkDrop {VERSION} for Windows 10/11
======================================

Convert iPhone HEIC photos to JPG and shrink photos and videos.
Everything happens on your PC - nothing is uploaded.

INSTALL
1. Right-click the zip > Extract All... (don't run it from inside the zip).
2. Double-click "Install ShrinkDrop.cmd".
   If Windows says "Windows protected your PC", click "More info" > "Run anyway".
   (ShrinkDrop is a small indie app that isn't code-signed yet.)
3. ShrinkDrop opens and is added to your Desktop and Start menu.

USE
- Drop photos, videos or whole folders onto the window, then click Shrink.
- Or right-click a photo or video in File Explorer > "Shrink with ShrinkDrop"
  (on Windows 11: Show more options first).
- Your originals are never changed. New files are saved next to them:
  IMG_1234.HEIC -> IMG_1234.jpg, IMG_1235.MOV -> IMG_1235 (small).mp4

SMART APP CONTROL
If your PC has Smart App Control turned on and blocks this download,
get ShrinkDrop from the Microsoft Store instead (search "ShrinkDrop").

UNINSTALL
Double-click "Uninstall ShrinkDrop.cmd".

Licence: GNU GPL v3 (see ShrinkDrop\\app\\LICENSE and THIRD_PARTY_NOTICES.txt)
Source code and support: https://github.com/tiger1247/shrinkdrop
"""


def clear(path):
    for _ in range(5):
        if not os.path.exists(path):
            return
        try:
            shutil.rmtree(path)
        except OSError:
            time.sleep(2)
    os.rename(path, f"{path}-old-{int(time.time())}")


def main():
    clear(STAGE)
    app_root = os.path.join(STAGE, "ShrinkDrop")
    os.makedirs(app_root)
    print("Bundling Python runtime…")
    bm.copy_python(os.path.join(app_root, "python"))
    bm.copy_app(os.path.join(app_root, "app"))
    with open(os.path.join(app_root, "app", "DIRECT_EDITION"), "w") as fh:
        fh.write(VERSION)
    compileall.compile_dir(app_root, quiet=1, workers=0)
    for name, text in (("Install ShrinkDrop.cmd", INSTALL_CMD), ("Uninstall ShrinkDrop.cmd", UNINSTALL_CMD),
                       ("READ ME FIRST.txt", README)):
        with open(os.path.join(STAGE, name), "w", encoding="ascii", newline="\r\n") as fh:
            fh.write(text)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _, files in os.walk(STAGE):
            for fn in files:
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, STAGE))
    print(f"Wrote {OUT} ({os.path.getsize(OUT) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
