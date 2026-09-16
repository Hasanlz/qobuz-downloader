# Quaver bootstrap — download the project and start the setup wizard.
#
#   powershell -c "irm https://raw.githubusercontent.com/Hasanlz/qobuz-downloader/main/bootstrap.ps1 | iex"
#
# Override with env: QUAVER_REPO_URL, QUAVER_REF (default main), QUAVER_HOME
# (default $env:USERPROFILE\quaver). Extra arguments reach wizard.py (--defaults).

$ErrorActionPreference = 'Stop'

$RepoUrl = if ($env:QUAVER_REPO_URL) { $env:QUAVER_REPO_URL } else { 'https://github.com/Hasanlz/qobuz-downloader.git' }
$Ref     = if ($env:QUAVER_REF)     { $env:QUAVER_REF }     else { 'main' }
$Dest    = if ($env:QUAVER_HOME)    { $env:QUAVER_HOME }    else { Join-Path $env:USERPROFILE 'quaver' }
$RepoWeb = ($RepoUrl -replace '\.git$', '')

function Say([string]$m)   { Write-Host "  $m" }
function Good([string]$m)  { Write-Host "  ✓ $m" -ForegroundColor Green }
function Fail([string]$m)  { Write-Host "  ✗ $m" -ForegroundColor Red; exit 1 }

Write-Host ''
Write-Host '  Quaver bootstrap' -ForegroundColor Bold

# 1. Python 3.12+ — prefer the py launcher, fall back to python on PATH
$Py = $null
foreach ($cand in @(@('py', '-3.13'), @('py', '-3.12'), @('python',))) {
    try {
        $probe = & $cand[0] @($cand[1..($cand.Length - 1)] | Where-Object { $_ }) `
            '-c' 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) {
            $Py = if ($cand.Count -gt 1) { , @($cand[0], $cand[1]) } else { , @($cand[0]) }
            break
        }
    } catch { }
}
if (-not $Py) {
    Fail @"
Python 3.12+ not found. Install it first:
    winget install Python.Python.3.12
(then re-run this command)
"@
}
Good ("python: " + ((& $Py[0] @($Py[1..($Py.Length - 1)] | Where-Object { $_ }) '--version' 2>&1) -join ''))

# 2. Get the repository — git if available, otherwise download the zipball
if (Get-Command git -ErrorAction SilentlyContinue) {
    if (Test-Path (Join-Path $Dest '.git')) {
        Say "updating existing checkout → $Dest"
        & git -C $Dest fetch --depth 1 origin $Ref 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail 'git fetch failed — check network / QUAVER_REF' }
        & git -C $Dest checkout -q FETCH_HEAD 2>&1 | Out-Null
    } elseif (Test-Path $Dest) {
        Fail "$Dest exists but is not a git checkout — remove it or set QUAVER_HOME"
    } else {
        Say "cloning $RepoUrl ($Ref) → $Dest"
        & git clone --quiet --depth 1 --branch $Ref $RepoUrl $Dest
        if ($LASTEXITCODE -ne 0) { Fail 'git clone failed' }
    }
} else {
    Say "git not found — downloading the zipball instead"
    $Zip = Join-Path $env:TEMP 'quaver-download.zip'
    $Tmp = Join-Path $env:TEMP 'quaver-download'
    Remove-Item $Zip, $Tmp -Recurse -Force -ErrorAction SilentlyContinue
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri "$RepoWeb/archive/refs/heads/$Ref.zip" -OutFile $Zip -UseBasicParsing
    Expand-Archive -Path $Zip -DestinationPath $Tmp -Force
    $Inner = Get-ChildItem $Tmp -Directory | Select-Object -First 1
    if (-not $Inner) { Fail 'zipball extraction failed' }
    if (Test-Path $Dest) { Remove-Item $Dest -Recurse -Force }
    Move-Item $Inner.FullName $Dest
    Remove-Item $Zip, $Tmp -Recurse -Force -ErrorAction SilentlyContinue
}
Good 'repository ready'

# 3. The wizard does the rest: venv, pip installs, credentials, settings, PATH
Write-Host ''
& $Py[0] @($Py[1..($Py.Length - 1)] | Where-Object { $_ }) (Join-Path $Dest 'wizard.py') @args
exit $LASTEXITCODE
