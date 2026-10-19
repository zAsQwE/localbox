# PowerShell 5.1: official Node.js LTS downloads, with an MSI fallback.
function Get-NodeDownload([string]$Kind) {
    $checksums = Invoke-RestMethod 'https://nodejs.org/dist/latest-v24.x/SHASUMS256.txt' -TimeoutSec 30
    $pattern = if ($Kind -eq 'msi') { 'node-(v[0-9.]+)-x64.msi' } else { 'node-(v[0-9.]+)-win-x64.zip' }
    $match = [regex]::Match($checksums, '(?m)^([a-f0-9]{64})\s+(' + $pattern.Replace('.', '\.') + ')\s*$')
    if (-not $match.Success) { throw "Не найден официальный Node.js LTS ($Kind)." }
    return @{name=$match.Groups[2].Value; hash=$match.Groups[1].Value;
             url=('https://nodejs.org/dist/' + $match.Groups[3].Value + '/' + $match.Groups[2].Value)}
}

function Install-NodeArchive {
    $download = Get-NodeDownload 'zip'
    $archive = Join-Path $cache $download.name
    Download-File $download.url $archive $download.hash
    $stage = Join-Path $cache ('node-extracted-' + [guid]::NewGuid().ToString('N'))
    $destination = Join-Path $runtime 'node'
    $backup = Join-Path $runtime ('node-backup-' + [guid]::NewGuid().ToString('N'))
    $replaced = $false
    try {
        Expand-Archive -LiteralPath $archive -DestinationPath $stage
        $folder = Join-Path $stage $download.name.Replace('.zip', '')
        if (-not (Get-NodeTools (Join-Path $folder 'node.exe'))) { throw 'Официальный архив Node.js не прошёл проверку Node/npm.' }
        if (Test-Path -LiteralPath $destination) {
            if ((Get-Item -LiteralPath $destination -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Папка runtime/node является ссылкой.' }
            Move-Item -LiteralPath $destination -Destination $backup
        }
        try {
            Move-Item -LiteralPath $folder -Destination $destination
            $replaced = $true
            if (-not (Get-NodeTools (Join-Path $destination 'node.exe'))) { throw 'Node/npm не прошли проверку после замены папки.' }
        } catch {
            if ($replaced -and (Test-Path -LiteralPath $destination)) { Remove-Item -LiteralPath $destination -Recurse -Force }
            if (Test-Path -LiteralPath $backup) { Move-Item -LiteralPath $backup -Destination $destination }
            throw
        }
        if (Test-Path -LiteralPath $backup) { Write-Host "Предыдущая папка Node.js сохранена: $backup" }
    } finally {
        if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    }
}

function Install-NodeMsi {
    $download = Get-NodeDownload 'msi'
    $file = Join-Path $cache $download.name
    Download-File $download.url $file $download.hash
    if ((Get-AuthenticodeSignature -LiteralPath $file).Status -ne 'Valid') {
        throw 'Не удалось проверить цифровую подпись установщика Node.js.'
    }
    Write-Host 'Устанавливаю официальный MSI Node.js. Windows может запросить права администратора.'
    $process = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\msiexec.exe') `
        -ArgumentList "/i `"$file`" /passive /norestart" -Verb RunAs -Wait -PassThru
    if ($process.ExitCode -notin @(0, 3010, 1641, 1638)) {
        throw "Установщик Node.js завершился с кодом $($process.ExitCode)."
    }
}

function Ensure-Node {
    $tools = Find-Node
    if ($tools) { return $tools }
    try {
        Install-NodeArchive
        $tools = Find-Node
        if (-not $tools) { throw 'В распакованном Node.js не работают node или npm.' }
        return $tools
    } catch {
        Write-Host "Не удалось установить архив Node.js: $_"
        Write-Host 'Повторно проверяю установленный Node.js и npm...'
        $tools = Find-Node
        if ($tools) { return $tools }
    }
    try {
        Write-Host 'Использую установщик из инструкции https://nodejs.org/en/download'
        Install-NodeMsi
        $tools = Find-Node
        if (-not $tools) { throw 'Node.js 18+ с рабочим npm не найден после установки MSI.' }
        return $tools
    } catch {
        $failure = $_
        $tools = Find-Node
        if ($tools) { return $tools }
        throw "Не удалось установить Node.js: $failure Инструкция: https://nodejs.org/en/download"
    }
}
