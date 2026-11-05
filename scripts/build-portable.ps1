param([switch]$SkipFrontend, [string]$OutputDirectory = 'dist')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot 'env\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Crie o ambiente env e instale requirements-dev.txt primeiro.' }
if (-not $SkipFrontend) {
    Push-Location frontend
    try {
        npm ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar o frontend.' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Falha ao compilar o frontend.' }
    } finally { Pop-Location }
}
New-Item -ItemType Directory -Force build | Out-Null
# Ferramentas do importador do YouTube: ffmpeg/ffprobe (mesclar e verificar o vídeo) e node (desafios JavaScript do yt-dlp).
$tools = Join-Path $projectRoot 'build\tools'
$ffmpegZip = 'ffmpeg-n9.0-latest-win64-lgpl-shared-9.0.zip'
$ffmpegBase = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest'
$nodeBase = 'https://nodejs.org/dist/latest-v24.x'
function Get-Text([string]$Url) {
    $file = Join-Path $projectRoot 'build\download.txt'
    Invoke-WebRequest -UseBasicParsing $Url -OutFile $file
    try { return Get-Content -LiteralPath $file } finally { Remove-Item -LiteralPath $file }
}
function Get-Verified([string]$Url, [string]$Name, [string]$SumsUrl) {
    $target = Join-Path $projectRoot "build\$Name"
    $expected = (Get-Text $SumsUrl | Where-Object { $_ -match "\s\*?$([regex]::Escape($Name))$" } | Select-Object -First 1) -replace '\s.*$', ''
    if (-not $expected) { throw "Checksum de $Name não encontrado." }
    if (-not (Test-Path -LiteralPath $target) -or (Get-FileHash $target -Algorithm SHA256).Hash -ne $expected.ToUpper()) {
        Invoke-WebRequest -UseBasicParsing $Url -OutFile $target
        if ((Get-FileHash $target -Algorithm SHA256).Hash -ne $expected.ToUpper()) { throw "Checksum inválido para $Name." }
    }
    return $target
}
if (-not (Test-Path -LiteralPath (Join-Path $tools 'ffmpeg.exe')) -or -not (Test-Path -LiteralPath (Join-Path $tools 'node.exe'))) {
    Remove-Item -Recurse -Force -LiteralPath $tools -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force $tools | Out-Null
    $ffmpeg = Get-Verified "$ffmpegBase/$ffmpegZip" $ffmpegZip "$ffmpegBase/checksums.sha256"
    $nodeName = (Get-Text "$nodeBase/SHASUMS256.txt" | Where-Object { $_ -match 'node-v[\d.]+-win-x64\.zip$' } | Select-Object -First 1) -replace '^\S+\s+', ''
    $node = Get-Verified "$nodeBase/$nodeName" $nodeName "$nodeBase/SHASUMS256.txt"
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($ffmpeg)
    try {
        foreach ($entry in $archive.Entries) {
            if ($entry.FullName -match '/bin/(ffmpeg\.exe|ffprobe\.exe|[a-z]+-\d+\.dll)$') {
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $tools $entry.Name), $true)
            }
        }
    } finally { $archive.Dispose() }
    $archive = [IO.Compression.ZipFile]::OpenRead($node)
    try {
        $entry = $archive.Entries | Where-Object { $_.FullName -match '/node\.exe$' } | Select-Object -First 1
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, (Join-Path $tools 'node.exe'), $true)
    } finally { $archive.Dispose() }
}
foreach ($name in 'ffmpeg', 'ffprobe', 'node') {
    & (Join-Path $tools "$name.exe") -version *> $null
    if ($LASTEXITCODE -ne 0) { & (Join-Path $tools "$name.exe") --version *> $null }
    if ($LASTEXITCODE -ne 0) { throw "Ferramenta inválida: $name.exe" }
}
& $pythonExe -c "from app.desktop import icon_image; icon_image(256).save('build/lua.ico', sizes=[(16,16),(32,32),(48,48),(128,128),(256,256)])"
if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar ícone.' }
& $pythonExe -m PyInstaller --noconfirm --onefile --windowed --distpath $OutputDirectory --name Lua-MediaPaper --icon build/lua.ico --add-data 'static;static' --add-binary 'build/tools;tools' --collect-all yt_dlp_ejs --hidden-import yt_dlp --collect-all reportlab --collect-all app --collect-all mediapaper --collect-all pypdf --hidden-import django.template.defaulttags --hidden-import django.template.defaultfilters --hidden-import django.template.loader_tags --hidden-import django.templatetags.static --hidden-import whitenoise.middleware --hidden-import pystray._win32 launcher.py
if ($LASTEXITCODE -ne 0) { throw 'Falha ao gerar executável.' }
Write-Output "Pronto: $OutputDirectory\Lua-MediaPaper.exe"
