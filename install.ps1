param(
    [string]$Repository = 'https://github.com/PearcePin/valbot.git',
    [string]$Destination = (Join-Path $env:USERPROFILE 'valbot'),
    [switch]$Local,
    [switch]$NoSetup
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'Install Git for Windows from https://git-scm.com/download/win, reopen PowerShell, then rerun.'
    }
    winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Git installation failed. Install Git for Windows and reopen PowerShell.' }
    $GitSystem = Join-Path $env:ProgramFiles 'Git\cmd'
    $GitUser = Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd'
    $env:PATH = "$GitSystem;$GitUser;$env:PATH"
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git installed. Reopen PowerShell, then rerun.' }
}
if ($Local) {
    $Destination = $PSScriptRoot
} elseif (-not (Test-Path -LiteralPath $Destination)) {
    git clone -- $Repository $Destination
    if ($LASTEXITCODE -ne 0) { throw 'Git clone failed. Check repository access.' }
} else {
    $Changes = git -C $Destination status --porcelain
    if ($LASTEXITCODE -ne 0 -or $Changes) { throw 'Local source changes found; commit/stash first. Keep data/.' }
    git -C $Destination pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw 'Git update failed. Keep data/ and check repository access.' }
    Write-Host 'Updated existing checkout; data/ settings are preserved.'
}
if (-not (Test-Path -LiteralPath (Join-Path $Destination 'setup.py'))) { throw 'Destination is not a valbot project.' }
$Destination = (Resolve-Path -LiteralPath $Destination).ProviderPath
Push-Location -LiteralPath $Destination
try {
    Write-Host '[1/3] Preparing compatible Python (system Python is left intact)...'
    $VenvRoot = [IO.Path]::GetFullPath((Join-Path $Destination '.venv'))
    $VenvPython = Join-Path $VenvRoot 'Scripts\python.exe'
    $Compatible = $false
    if (Test-Path -LiteralPath $VenvPython) {
        & $VenvPython -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info < (3,14) else 1)' 2>$null
        $Compatible = $LASTEXITCODE -eq 0
    }
    if (-not $Compatible) {
        if (Test-Path -LiteralPath $VenvRoot) {
            # Validate the resolved target before moving any existing environment.
            $Prefix = $Destination.TrimEnd('\') + '\'
            if (-not $VenvRoot.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid venv location.' }
            $Backup = Join-Path $Destination ('.venv.backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
            Move-Item -LiteralPath $VenvRoot -Destination $Backup
            Write-Host "Old venv backed up: $Backup"
        }
        $UvCommand = Get-Command uv -ErrorAction SilentlyContinue
        $Uv = if ($UvCommand) { $UvCommand.Source } else { Join-Path $env:USERPROFILE '.local\bin\uv.exe' }
        if (-not (Test-Path -LiteralPath $Uv)) {
            $UvInstaller = Join-Path ([IO.Path]::GetTempPath()) ('valbot-uv-' + [guid]::NewGuid().ToString('N') + '.ps1')
            Invoke-WebRequest -UseBasicParsing 'https://astral.sh/uv/install.ps1' -OutFile $UvInstaller
            $PreviousInstallDir = $env:UV_INSTALL_DIR
            $PreviousModify = $env:UV_NO_MODIFY_PATH
            try {
                $env:UV_INSTALL_DIR = Join-Path $env:USERPROFILE '.local\bin'
                $env:UV_NO_MODIFY_PATH = '1'
                powershell -NoProfile -ExecutionPolicy Bypass -File $UvInstaller
                if ($LASTEXITCODE -ne 0) { throw 'uv installation failed.' }
            } finally {
                $env:UV_INSTALL_DIR = $PreviousInstallDir
                $env:UV_NO_MODIFY_PATH = $PreviousModify
                Remove-Item -LiteralPath $UvInstaller -ErrorAction SilentlyContinue
            }
        }
        & $Uv venv --python 3.12 --seed .venv
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 / venv creation failed. See docs/install.md.' }
    }
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
    & $VenvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $VenvPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
    Write-Host '[2/3] Riot / LINE configuration...'
    if (-not $NoSetup) {
        & $VenvPython -c 'from valbot.storage import load_config; load_config()' 2>$null
        $HasConfig = $LASTEXITCODE -eq 0
        $Keep = if ($HasConfig) { Read-Host 'Keep existing Riot/LINE settings? [Y/n]' } else { 'n' }
        if ($HasConfig -and $Keep -ne 'n') { & $VenvPython setup.py --schedule-only }
        else { & $VenvPython setup.py }
        if ($LASTEXITCODE -ne 0) { throw 'Setup incomplete; data/ is preserved. Run .venv\Scripts\python.exe setup.py again. See docs/install.md.' }
    }
    Write-Host '[3/3] Preparing Cloudflare Tunnel...'
    & $VenvPython -c 'from valbot.storage import Vault; Vault()'
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare private data directory.' }
    $Binary = Join-Path $Destination 'data\cloudflared.exe'
    if (-not (Test-Path -LiteralPath $Binary)) {
        # Cloudflare publishes Windows amd64/386 binaries, not a Windows ARM64 download.
        if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
            throw 'Automatic cloudflared setup supports x64/x86 Windows. On ARM use a compatible emulated binary or Ubuntu; see docs/install.md.'
        }
        $Arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'x86' -and -not $env:PROCESSOR_ARCHITEW6432) { '386' } else { 'amd64' }
        $Download = Join-Path $Destination ('data\cloudflared-' + [guid]::NewGuid().ToString('N') + '.exe')
        Invoke-WebRequest -UseBasicParsing "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-$Arch.exe" -OutFile $Download
        & $Download --version
        if ($LASTEXITCODE -ne 0) { throw 'cloudflared validation failed.' }
        Move-Item -LiteralPath $Download -Destination $Binary
    }
    Write-Host 'Installation complete. To start the Bot + Tunnel and update the LINE webhook:'
    Write-Host "cd `"$Destination`""
    Write-Host '.\.venv\Scripts\python.exe -m valbot.daemon'
    Write-Host 'Keep this terminal open on Windows. Ubuntu service mode can close the terminal.'
    Write-Host 'Enable Use webhook and disable LINE default auto-reply. Detailed guide: docs/install.md'
} finally { Pop-Location }
