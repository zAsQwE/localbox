# PowerShell 5.1; пути читаем как данные, в том числе при отдельной папке runtime.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$manifest = Join-Path $root 'launcher\install-paths.json'
$python = $null
if (Test-Path -LiteralPath $manifest) {
    $config = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($config.python -and (Test-Path -LiteralPath $config.python)) { $python = $config.python }
    elseif ($config.runtime -and (Test-Path -LiteralPath (Join-Path $config.runtime 'python\python.exe'))) {
        $python = Join-Path $config.runtime 'python\python.exe'
    }
}
if (-not $python) {
    $bundled = Join-Path $root 'runtime\python\python.exe'
    if (Test-Path -LiteralPath $bundled) { $python = $bundled }
}
if (-not $python) {
    foreach ($name in @('python', 'py')) {
        $found = Get-Command $name -ErrorAction SilentlyContinue
        if ($found) {
            try {
                if ($name -eq 'py') { $output = & $found.Source -3 -c 'import sys; print(sys.executable)' 2>$null }
                else { $output = & $found.Source -c 'import sys; print(sys.executable)' 2>$null }
                if ($LASTEXITCODE -eq 0 -and $output -and (Test-Path -LiteralPath $output)) { $python = $output; break }
            } catch { continue }
        }
    }
}
if (-not $python) { Write-Host 'Python не найден. Запустите setup.exe или install.bat.'; exit 1 }
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
& $python (Join-Path $root 'launcher\start.py') @args
exit $LASTEXITCODE
