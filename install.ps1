param(
    [string]$Repository = 'https://github.com/PearcePin/valbot.git',
    [string]$Destination = (Join-Path $env:USERPROFILE 'valbot')
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Install Git for Windows first.' }
if (Test-Path -LiteralPath $Destination) { throw "Destination already exists: $Destination" }
if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = 'py'
    $PythonArgs = @('-3')
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = 'python'
    $PythonArgs = @()
} else { throw 'Install Python 3.11+ first (enable Add Python to PATH).' }
& $PythonCommand @PythonArgs -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
git clone -- $Repository $Destination
if ($LASTEXITCODE -ne 0) { throw 'Git clone failed. Check repository access.' }
Push-Location -LiteralPath $Destination
try {
    & $PythonCommand @PythonArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'venv creation failed.' }
    $VenvPython = Join-Path $Destination '.venv\Scripts\python.exe'
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
    & $VenvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $VenvPython setup.py
    if ($LASTEXITCODE -ne 0) { throw 'Setup incomplete. Run .venv\Scripts\python.exe setup.py again.' }
} finally { Pop-Location }
