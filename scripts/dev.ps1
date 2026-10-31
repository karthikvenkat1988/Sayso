# Sets up a virtual environment, installs Sayso in editable mode and runs it. No admin rights needed.
param([switch]$NoRun, [string]$Extras = "full,dev")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path ".venv")) { py -3.12 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[$Extras]"
if (-not $NoRun) { & .\.venv\Scripts\python.exe -m sayso --portable }
