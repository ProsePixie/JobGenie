@echo off
REM Run by the "JobSearchV1 Watcher" Windows scheduled task (see tools/setup_scheduler.md).
REM A plain checked-in wrapper rather than logic buried in the task's own XML, so it can
REM be read, edited, and run by hand the same way as everything else in tools/.
cd /d "%~dp0\.."
echo. >> data\watch-log.txt
echo ==== %date% %time% ==== >> data\watch-log.txt
py.exe tools\watch_ats.py --run >> data\watch-log.txt 2>&1
py.exe tools\watch_static.py --run >> data\watch-log.txt 2>&1
