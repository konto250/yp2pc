# iPadと同じLAN内で使う実験用サーバーです。Ctrl+Cで停止します。
param(
    [Parameter(Mandatory = $true)][string]$Address,
    [ValidateRange(1, 65535)][int]$Port = 3000
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = (Get-Command python -ErrorAction Stop).Source
}
Push-Location $projectRoot
try {
    & $pythonPath -X utf8 dev.py --host $Address --port $Port --base-url "http://${Address}:$Port"
    if ($LASTEXITCODE -ne 0) { throw 'サーバーを起動できませんでした。表示されたエラーを確認してください。' }
} finally {
    Pop-Location
}
