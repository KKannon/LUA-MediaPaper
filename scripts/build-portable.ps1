param([switch]$SkipFrontend, [string]$OutputDirectory = 'dist')
$ErrorActionPreference = 'Stop'
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
& $pythonExe -c "from app.desktop import icon_image; icon_image(256).save('build/lua.ico', sizes=[(16,16),(32,32),(48,48),(128,128),(256,256)])"
if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar ícone.' }
& $pythonExe -m PyInstaller --noconfirm --onefile --windowed --distpath $OutputDirectory --name Lua-MediaPaper --icon build/lua.ico --add-data 'static;static' --collect-all reportlab --collect-all app --collect-all mediapaper --collect-all pypdf --hidden-import django.template.defaulttags --hidden-import django.template.defaultfilters --hidden-import django.template.loader_tags --hidden-import django.templatetags.static --hidden-import whitenoise.middleware --hidden-import pystray._win32 launcher.py
if ($LASTEXITCODE -ne 0) { throw 'Falha ao gerar executável.' }
Write-Output "Pronto: $OutputDirectory\Lua-MediaPaper.exe"
