@echo off
rem First-run helper for Windows (Command Prompt).
rem
rem 1. If profile\ does not exist, copies the fictional example (profile.example\)
rem    to profile\ so the app can be tried. An existing profile\ is never touched.
rem 2. Runs tools\doctor.py, which checks Python, Chrome/Edge, poppler and the
rem    Claude Code CLI and says how to fix anything missing. It installs nothing.
rem
rem It does not install packages and does not start the app. It exits non-zero
rem when the doctor finds a required tool missing, or the profile copy fails.
setlocal
cd /d "%~dp0"

if not exist "profile.example\" (
    echo profile.example\ is missing from %CD%. Is this a complete JobGenie checkout?
    exit /b 1
)

where py >nul 2>nul
if errorlevel 1 (
    echo The Python launcher "py" was not found. Install Python 3.10 or newer from
    echo python.org and tick "Add python.exe to PATH", then run this again.
    exit /b 1
)

echo == Profile ==
if exist "profile\" (
    echo profile\ already exists and was left exactly as it is.
) else (
    xcopy "profile.example" "profile\" /E /I /Q >nul
    if errorlevel 1 (
        echo Could not copy profile.example to profile. Nothing else was changed.
        exit /b 1
    )
    echo Copied the fictional example ^(Jane Doe^) to profile\, so you can try the app.
    echo When you are ready to use your own data, see step 3 below.
)
echo.

echo == Checking your tools ==
py tools\doctor.py
set "DOCTOR=%ERRORLEVEL%"
echo.

echo == Next steps ==
echo 1. Fix anything the check above marked MISSING (Chrome, pdftotext, Python).
echo 2. Try the app:          py web\server.py
echo 3. Use your own CV:      put it (PDF or DOCX) in inbox\, open this folder in
echo                          Claude Code and type /setup. To start from a blank
echo                          profile instead of Jane Doe, rename or remove profile\
echo                          first, then run: py tools\new_profile.py
echo Full guide: docs\SETUP.md
endlocal & exit /b %DOCTOR%
