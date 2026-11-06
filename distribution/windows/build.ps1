param(
    [string]$PythonExe,
    [string]$InnoCompiler,
    [string]$SevenZipExe,
    [string]$BuildDirectory,
    [string]$NodeExe = 'node',
    [string]$AppVersion = "1.0.1"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Build = if ($BuildDirectory) { [IO.Path]::GetFullPath($BuildDirectory) } else { Join-Path $Root 'build\windows' }
$Tools = Join-Path $Build 'tools'
$Downloads = Join-Path $Build 'downloads'
$Payload = Join-Path $Build 'payload'
$Output = Join-Path $Root 'dist'
$Lock = Get-Content -Raw (Join-Path $PSScriptRoot 'vendor-lock.json') | ConvertFrom-Json

if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
if ($AppVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'AppVersion must use major.minor.patch.' }
if (-not $PythonExe) { $PythonExe = Join-Path $Root 'backend\.venv\Scripts\python.exe' }
if (-not (Test-Path $PythonExe)) { throw 'Pass -PythonExe with a build-machine Python 3.11+ x64 interpreter.' }
foreach ($directory in @($Build, $Tools, $Downloads, $Output)) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

function Invoke-Checked {
    param([string]$File, [string[]]$Arguments)
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$File failed with exit code $LASTEXITCODE" }
}

function Get-VerifiedDownload {
    param($Entry, [string]$Name)
    $target = Join-Path $Downloads $Name
    if (-not (Test-Path $target)) {
        Write-Host "Downloading $Name"
        $previousProgress = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $Entry.url -OutFile "$target.partial" -TimeoutSec 300
            Move-Item "$target.partial" $target -Force
        } finally { $ProgressPreference = $previousProgress }
    }
    $actual = (Get-FileHash -LiteralPath $target -Algorithm $Entry.algorithm).Hash
    if ($actual -ne $Entry.hash) { throw "Integrity check failed: $Name. Remove it from downloads and retry." }
    return $target
}

function Assert-Publisher {
    param([string]$Path, [string]$Publisher)
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch $Publisher) {
        throw "Untrusted publisher/signature for $Path ($($signature.Status))."
    }
}

if ($SevenZipExe) {
    $Seven = (Resolve-Path -LiteralPath $SevenZipExe).Path
} else {
    $SevenBootstrap = Get-VerifiedDownload $Lock.sevenzipBootstrap '7zr.exe'
    $SevenInstaller = Get-VerifiedDownload $Lock.sevenzip '7zip-x64.exe'
    $SevenDirectory = Join-Path $Tools '7zip'
    if (-not (Test-Path (Join-Path $SevenDirectory '7z.exe'))) {
        Invoke-Checked $SevenBootstrap @('x', $SevenInstaller, "-o$SevenDirectory", '-y')
    }
    $Seven = Join-Path $SevenDirectory '7z.exe'
}
if (-not (Test-Path $Seven)) { throw '7-Zip extraction did not provide 7z.exe.' }

if (-not $InnoCompiler) {
    $innoDirectory = Join-Path $Tools 'inno'
    $InnoCompiler = Join-Path $innoDirectory 'ISCC.exe'
    if (-not (Test-Path $InnoCompiler)) {
        $setup = Get-VerifiedDownload $Lock.inno 'inno-setup.exe'
        Assert-Publisher $setup 'Pyrsys|Jordan Russell'
        $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', '/NOICONS',
                       "/DIR=`"$innoDirectory`"", "/LOG=`"$(Join-Path $Build 'inno-bootstrap.log')`"")
        $installation = Start-Process -FilePath $setup -ArgumentList $arguments -Wait -PassThru
        if ($installation.ExitCode -ne 0) { throw "Compiler setup failed: $($installation.ExitCode)." }
    }
}
if (-not (Test-Path $InnoCompiler)) { throw 'Inno compiler not found. Pass -InnoCompiler.' }

$BuildPython = Join-Path $Build 'venv\Scripts\python.exe'
if (-not (Test-Path $BuildPython)) { Invoke-Checked $PythonExe @('-m', 'venv', (Join-Path $Build 'venv')) }
Invoke-Checked $BuildPython @('-c', "import struct,sys; assert struct.calcsize('P')==8 and sys.version_info >= (3,11)")
Invoke-Checked $BuildPython @('-m', 'pip', 'install', '-r', (Join-Path $PSScriptRoot 'build-requirements.txt'))

if (Test-Path $Payload) { Remove-Item -Recurse -Force -LiteralPath $Payload }
New-Item -ItemType Directory -Force -Path $Payload | Out-Null
Invoke-Checked $BuildPython @((Join-Path $PSScriptRoot 'build_assets.py'), $Root, $Build, $Payload)

$oldIcon = [Environment]::GetEnvironmentVariable('BMA_BUILD_ICON')
$env:BMA_BUILD_ICON = Join-Path $Build 'planning.ico'
try {
    Invoke-Checked $BuildPython @('-m', 'PyInstaller', '--noconfirm', '--clean',
        '--distpath', (Join-Path $Build 'frozen'), '--workpath', (Join-Path $Build 'pyinstaller'),
        (Join-Path $PSScriptRoot 'PlanningScheduling.spec'))
} finally { [Environment]::SetEnvironmentVariable('BMA_BUILD_ICON', $oldIcon) }
Copy-Item -Recurse -Force -Path (Join-Path $Build 'frozen\PlanningScheduling\*') -Destination $Payload

$nodeVersion = (& $NodeExe --version).Trim()
if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch '^v(22|24)\.\d+\.\d+$') {
    throw 'Build with a supported Node.js 22 or 24 LTS x64 release.'
}
$nodeArchive = "node-$nodeVersion-win-x64.zip"
$nodeSums = (Invoke-WebRequest -UseBasicParsing -Uri "https://nodejs.org/dist/$nodeVersion/SHASUMS256.txt" -TimeoutSec 60).Content
$nodeLine = @($nodeSums -split "`n" | Where-Object { $_.Trim().EndsWith("  $nodeArchive") })
if ($nodeLine.Count -ne 1) { throw 'Node archive not found in official checksums.' }
$nodeEntry = @{url="https://nodejs.org/dist/$nodeVersion/$nodeArchive"; algorithm='SHA256'; hash=($nodeLine[0] -split '\s+')[0]}
$nodeZip = Get-VerifiedDownload $nodeEntry $nodeArchive
$nodeTools = Join-Path $Tools "node-$nodeVersion"
if (-not (Test-Path $nodeTools)) { Expand-Archive -LiteralPath $nodeZip -DestinationPath $nodeTools }
$nodeSource = Join-Path $nodeTools "node-$nodeVersion-win-x64"
Assert-Publisher (Join-Path $nodeSource 'node.exe') 'OpenJS|Node.js'
New-Item -ItemType Directory -Force -Path (Join-Path $Payload 'runtime'), (Join-Path $Payload 'licenses\node') | Out-Null
Copy-Item (Join-Path $nodeSource 'node.exe') (Join-Path $Payload 'runtime\node.exe')
Copy-Item (Join-Path $nodeSource 'LICENSE') (Join-Path $Payload 'licenses\node\LICENSE')

Invoke-Checked $NodeExe @((Join-Path $PSScriptRoot 'build_frontend.cjs'), $Build, 'standalone')

$firefoxArchive = Get-VerifiedDownload $Lock.firefox 'firefox-esr.exe'
Assert-Publisher $firefoxArchive 'Mozilla'
$firefoxExtract = Join-Path $Build 'firefox-extracted'
if (Test-Path $firefoxExtract) { Remove-Item -Recurse -Force -LiteralPath $firefoxExtract }
Invoke-Checked $Seven @('x', $firefoxArchive, "-o$firefoxExtract", '-y')
New-Item -ItemType Directory -Force -Path (Join-Path $Payload 'browser') | Out-Null
Copy-Item -Recurse -Force -Path (Join-Path $firefoxExtract 'core') -Destination (Join-Path $Payload 'browser\firefox')
$policyDirectory = Join-Path $Payload 'browser\firefox\distribution'
New-Item -ItemType Directory -Force -Path $policyDirectory | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'firefox-policies.json') (Join-Path $policyDirectory 'policies.json')
$geckoZip = Get-VerifiedDownload $Lock.geckodriver 'geckodriver-win64.zip'
Expand-Archive -LiteralPath $geckoZip -DestinationPath (Join-Path $Payload 'browser') -Force
New-Item -ItemType Directory -Force -Path (Join-Path $Payload 'licenses\geckodriver') | Out-Null
Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/mozilla/geckodriver/v$($Lock.geckodriver.version)/LICENSE" -OutFile (Join-Path $Payload 'licenses\geckodriver\LICENSE') -TimeoutSec 60
Copy-Item (Join-Path $PSScriptRoot 'DISTRIBUTION-NOTICE.txt') $Payload
Invoke-Checked $BuildPython @((Join-Path $PSScriptRoot 'build_assets.py'), $Root, $Build, $Payload)

$forbidden = @(Get-ChildItem -LiteralPath $Payload -Recurse -Force -File | Where-Object {
    $_.Extension -in @('.db', '.sqlite', '.sqlite3', '.pfx', '.p12', '.key') -or
    $_.Name -like '.env*' -or $_.Name -in @('cookies.sqlite', 'logins.json', 'key4.db') -or
    $_.FullName -match '\\FirefoxProfile\\|\\uploads\\' -or
    ($_.FullName -match '\\database\\data\\' -and $_.Name -ne 'funcionario.json')
})
if ($forbidden.Count) { throw "Personal or writable artifacts in payload: $($forbidden.FullName -join ', ')" }

foreach ($mode in @('self-test', 'smoke-test')) {
    $report = Join-Path $Build "$mode.json"
    Remove-Item -LiteralPath $report -Force -ErrorAction SilentlyContinue
    $validation = Start-Process -FilePath (Join-Path $Payload 'PlanningScheduling.exe') -ArgumentList @("--$mode", '--report', "`"$report`"") -PassThru
    if (-not $validation.WaitForExit(180000)) { $validation.Kill(); throw "$mode timed out." }
    if ($validation.ExitCode -ne 0 -or -not (Test-Path $report)) { throw "$mode failed. Read $report" }
    if (-not (Get-Content -Raw $report | ConvertFrom-Json).ok) { throw "$mode failed. Read $report" }
    Write-Host "$mode passed"
}

$manifest = [ordered]@{
    application='Planning & Scheduling Michelin'; version=$AppVersion;
    builtUtc=[DateTime]::UtcNow.ToString('o'); node=$nodeVersion;
    firefox=$Lock.firefox.version; geckodriver=$Lock.geckodriver.version;
    vendorLock=$Lock; validation=@('self-test', 'smoke-test');
    files=@(Get-ChildItem -LiteralPath $Payload -Recurse -File | ForEach-Object {
        @{path=$_.FullName.Substring($Payload.Length + 1).Replace('\','/'); sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
    })
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 (Join-Path $Payload 'distribution-manifest.json')
Invoke-Checked $InnoCompiler @("/DPayloadDir=$Payload", "/DBuildDir=$Build", "/DOutputDir=$Output", "/DAppVersion=$AppVersion", (Join-Path $PSScriptRoot 'installer.iss'))
$setupPath = Join-Path $Output "Planning-Scheduling-Setup-$AppVersion.exe"
Get-FileHash -LiteralPath $setupPath -Algorithm SHA256 | Format-List
Write-Host "Installer ready: $setupPath"