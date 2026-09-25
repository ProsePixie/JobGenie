# The daily watcher task

A Windows Scheduled Task named **"JobSearchV1 Watcher"** runs
`tools/scheduled_watch.bat` once a day at 08:30, which runs
`py tools/watch_ats.py --run` and appends its output to `data/watch-log.txt`
with a timestamp. Set up 2026-09-21, because clicking "Check for new roles"
by hand was the only way it ever ran.

It runs in "Interactive only" mode: only while the machine is on and someone
is logged in, never while locked out or logged off, and it never asked for
or stored a password. That was deliberate - the alternative ("run whether
logged on or not") needs Windows to hold his account password, which is a
real credential to manage for a job that is not worth it.

## Check on it

```powershell
schtasks /query /tn "JobSearchV1 Watcher" /fo LIST /v
type data\watch-log.txt
```

## Change the time

```powershell
schtasks /change /tn "JobSearchV1 Watcher" /st 07:00
```

## Turn it off

```powershell
schtasks /delete /tn "JobSearchV1 Watcher" /f
```

Deleting the task does not touch `tools/scheduled_watch.bat` or
`tools/watch_ats.py` - running "Check for new roles" by hand in the app
still works exactly as before either way.
