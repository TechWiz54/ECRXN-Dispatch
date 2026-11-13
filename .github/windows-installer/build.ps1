<#
    Builds ECRXN-Dispatch-Setup-<version>.exe, the Windows installer. GitHub runs this for every release
    (.github/workflows/release.yml); you only need it to build one yourself.

    Needs: Windows, Python 3.12 (the same minor version as the bundled Python), Inno Setup 6 (iscc.exe).

      powershell -ExecutionPolicy Bypass -File .github\windows-installer\build.ps1 -Version 1.2.0

    The setup carries everything: the app, a private Python, its packages and ffmpeg, so nothing else
    needs installing on the computer it runs on.
#>
param(
    [string]$Version = '0.0.0',
    [string]$Python = 'python',
    [string]$PyVersion = '3.12.10',   # bundled Python: must be 3.12.x like $Python, so the compiled packages match
    [string]$Iscc = ''
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = Resolve-Path (Join-Path $Here '..\..')
$Build = Join-Path $Repo 'build\windows'
$Stage = Join-Path $Build 'stage'
$Cache = Join-Path $Build 'cache'
$Out = Join-Path $Repo 'dist'

function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Get-File($url, $dest) {
    if (-not (Test-Path $dest)) { Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing }
}

$pyMinor = & $Python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($pyMinor -ne ($PyVersion -replace '^(\d+\.\d+).*', '$1')) {
    throw "Use Python $PyVersion's minor version to build (found $pyMinor), so the packages match the bundled Python."
}

Remove-Item -Recurse -Force $Stage -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $Stage, $Cache, $Out | Out-Null

Step "Copying the app"
foreach ($f in 'app.py', 'serve.py', 'requirements.txt', 'LICENSE', 'README.md', '.env.example') {
    Copy-Item (Join-Path $Repo $f) $Stage
}
foreach ($d in 'lib', 'routes', 'templates', 'static', 'migrations', 'docs') {
    Copy-Item -Recurse (Join-Path $Repo $d) (Join-Path $Stage $d)
}
# never ship anyone's saved audio, and no byte-code caches
Get-ChildItem (Join-Path $Stage 'static\audio') -Force | Where-Object Name -ne '.gitkeep' | Remove-Item -Recurse -Force
Get-ChildItem $Stage -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
# every install starts blank: never ship a database, logs, settings or notes, even if a local build finds some
foreach ($p in 'var', 'log', '.env', 'HOW-IT-WORKS.md', 'public') {
    Remove-Item -Recurse -Force (Join-Path $Stage $p) -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Force (Join-Path $Stage 'windows') | Out-Null
Copy-Item (Join-Path $Here 'service.ps1'), (Join-Path $Here 'tray.py') (Join-Path $Stage 'windows')

Step "Bundling Python $PyVersion"
$embedZip = Join-Path $Cache "python-$PyVersion-embed-amd64.zip"
Get-File "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip" $embedZip
Expand-Archive $embedZip (Join-Path $Stage 'python') -Force
# let it import the app (..) and its packages (..\pydeps)
$pth = Get-ChildItem (Join-Path $Stage 'python') -Filter 'python*._pth' | Select-Object -First 1
$lines = (Get-Content $pth.FullName) | Where-Object { $_ -notmatch '^#?\s*import site' }
Set-Content $pth.FullName (@($lines) + @('..', '..\pydeps', 'import site')) -Encoding ascii

# the tray icon's settings window uses tkinter, which the embeddable Python leaves out: take it from $Python
Step "Adding tkinter"
$base = (& $Python -c "import sys; print(sys.base_prefix)").Trim()
$pyDir = Join-Path $Stage 'python'
Copy-Item -Recurse (Join-Path $base 'Lib\tkinter') (Join-Path $pyDir 'tkinter')
Remove-Item -Recurse -Force (Join-Path $pyDir 'tkinter\test') -ErrorAction SilentlyContinue
foreach ($dll in '_tkinter.pyd', 'tcl86t.dll', 'tk86t.dll', 'zlib1.dll') {
    $f = Join-Path $base "DLLs\$dll"
    if (Test-Path $f) { Copy-Item $f $pyDir }
}
New-Item -ItemType Directory -Force (Join-Path $pyDir 'tcl') | Out-Null
Get-ChildItem (Join-Path $base 'tcl') -Directory | Where-Object Name -match '^(tcl|tk)\d' |
    ForEach-Object { Copy-Item -Recurse $_.FullName (Join-Path $pyDir "tcl\$($_.Name)") }

Step "Installing packages"
& $Python -m pip install --disable-pip-version-check -q --target (Join-Path $Stage 'pydeps') -r (Join-Path $Repo 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
Get-ChildItem (Join-Path $Stage 'pydeps') -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force

Step "Bundling ffmpeg"
$ffZip = Join-Path $Cache 'ffmpeg-win64-gpl.zip'
Get-File 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip' $ffZip
$ffTmp = Join-Path $Cache 'ffmpeg'
Remove-Item -Recurse -Force $ffTmp -ErrorAction SilentlyContinue
Expand-Archive $ffZip $ffTmp -Force
$ffBin = Get-ChildItem $ffTmp -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1
New-Item -ItemType Directory -Force (Join-Path $Stage 'ffmpeg\bin') | Out-Null
Copy-Item $ffBin.FullName, (Join-Path $ffBin.DirectoryName 'ffprobe.exe') (Join-Path $Stage 'ffmpeg\bin')
$ffLicense = Get-ChildItem $ffTmp -Recurse -Filter 'LICENSE*' | Select-Object -First 1
if ($ffLicense) { Copy-Item $ffLicense.FullName (Join-Path $Stage 'ffmpeg\LICENSE.txt') }

Step "Checking the bundled app starts"
& (Join-Path $Stage 'python\python.exe') -c "import flask, waitress, bcrypt, pydub, icad_tone_detection, PIL, pystray, tkinter; print('imports ok, Tcl', tkinter.Tcl().eval('info patchlevel'))"
if ($LASTEXITCODE -ne 0) { throw "The bundled Python can't load the app's packages." }

Step "Building the setup program"
if (-not $Iscc) {
    $Iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
              "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Iscc) { throw "Inno Setup 6 (ISCC.exe) not found - install it from https://jrsoftware.org/isdl.php" }
& $Iscc "/DAppVersion=$Version" "/DStageDir=$Stage" "/DOutDir=$Out" (Join-Path $Here 'ECRXN-Dispatch.iss')
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Get-ChildItem $Out -Filter "ECRXN-Dispatch-Setup-$Version.exe" | ForEach-Object { Write-Host "Built $($_.FullName)" -ForegroundColor Green }
