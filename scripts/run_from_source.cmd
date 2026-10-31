@echo off
rem Starts Sayso with an approved Python when Sayso.exe is blocked by application control.
rem First time only:  py -3 -m pip install --user -r requirements-zipapp.txt
setlocal
set "HERE=%~dp0"
set "PYZ="
for %%F in ("%HERE%sayso-*.pyz") do set "PYZ=%%F"
if "%PYZ%"=="" (
  rem Running from a git checkout instead of a release folder.
  set "PYTHONPATH=%HERE%..\src"
  set "PYTHONW=pythonw"
  where pythonw >nul 2>nul || set "PYTHONW=pyw"
  start "" %PYTHONW% -m sayso %*
  exit /b 0
)
where pythonw >nul 2>nul && (start "" pythonw "%PYZ%" %* & exit /b 0)
where pyw >nul 2>nul && (start "" pyw -3 "%PYZ%" %* & exit /b 0)
echo Python was not found. Ask IT for the approved Python, or use the portable zip.
exit /b 1
