# PowerShell 5.1: download and verify release payloads without requiring Python.
$script:LocalBoxRepository = 'zAsQwE/localbox'
$script:LocalBoxReleaseBase = "https://github.com/$script:LocalBoxRepository/releases"
$script:LocalBoxMaxReleaseSize = 100MB

function Test-PayloadPath([string]$Name) {
    if (-not $Name -or $Name.Contains('\') -or $Name.Contains(':') -or $Name.StartsWith('/')) { return $false }
    $parts = $Name.Split('/')
    $excluded = @('node_modules','runtime','client','client-ru','certs','storage','cache','render','test','tests','__pycache__','build','dist','piper')
    foreach ($part in $parts) {
        if (-not $part -or $part.StartsWith('.') -or $part.StartsWith('test_') -or $part -in $excluded -or
            $part -match '[<>:"|?*]' -or $part.EndsWith('.') -or $part.EndsWith(' ') -or
            $part -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') { return $false }
    }
    if ($parts[-1] -in @('config.json','localbox-settings.json','install-paths.json','update-state.json','setup-options.ini','testing.md')) { return $false }
    if (@('LICENSE','README.md','start-server.sh','start-server.bat','setup.sh','install.bat','version.json') -ccontains $Name) { return $true }
    return $parts[0] -cin @('launcher','server','installer','tools','docs') -and [IO.Path]::GetExtension($Name) -cin @('.py','.js','.json','.md','.txt','.ps1','.sh','.nsi')
}

function Get-ReleaseVersion([string]$Version) {
    if ($Version -notmatch '^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$') { throw "Неверный номер версии Release: $Version" }
    return (@([int]$matches[1], [int]$matches[2], [int]$matches[3]) -join '.')
}

function Get-ReleaseAssetUrl($Asset) {
    $url = [string]$Asset.browser_download_url
    if (-not $url.StartsWith($script:LocalBoxReleaseBase + '/download/', [StringComparison]::Ordinal)) {
        throw 'Адрес файла не принадлежит Releases LocalBox.'
    }
    return $url
}

function Read-ReleaseText([string]$Url) {
    return Invoke-RestMethod -Uri $Url -Headers @{'User-Agent'='LocalBox-Setup'; 'Accept'='application/vnd.github+json'} -TimeoutSec 30
}

function Save-ReleaseArchive([string]$Url, [string]$File) {
    $request = [Net.HttpWebRequest]::Create($Url)
    $request.UserAgent = 'LocalBox-Setup'
    $request.Timeout = 30000
    $request.ReadWriteTimeout = 30000
    $response = $request.GetResponse()
    try {
        $input = $response.GetResponseStream()
        $output = [IO.File]::Create($File)
        try {
            $buffer = New-Object byte[] 131072
            $size = 0L
            while (($count = $input.Read($buffer, 0, $buffer.Length)) -gt 0) {
                $size += $count
                if ($size -gt $script:LocalBoxMaxReleaseSize) { throw 'Архив Release слишком большой.' }
                $output.Write($buffer, 0, $count)
            }
            if ($size -eq 0) { throw 'Скачан пустой архив Release.' }
        } finally { $output.Dispose(); $input.Dispose() }
    } finally { $response.Dispose() }
}

function Read-ZipText($Entry) {
    $reader = [IO.StreamReader]::new($Entry.Open(), [Text.Encoding]::UTF8)
    try { return $reader.ReadToEnd() }
    finally { $reader.Dispose() }
}

function Expand-VerifiedRelease([string]$Archive, [string]$Payload, [string]$Version) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $package = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        $entries = @($package.Entries)
        if ($entries.Count -gt 5000) { throw 'Слишком много файлов в Release.' }
        $names = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        $total = 0L
        foreach ($entry in $entries) {
            $total += $entry.Length
            $symlink = (($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000
            if (-not (Test-PayloadPath $entry.FullName) -or $symlink -or -not $names.Add($entry.FullName)) {
                throw "Недопустимый или повторяющийся путь Release: $($entry.FullName)"
            }
        }
        if ($total -gt $script:LocalBoxMaxReleaseSize) { throw 'Распакованный Release слишком большой.' }
        $manifestEntry = $package.GetEntry('installer/payload-sha256.json')
        if (-not $manifestEntry) { throw 'В Release нет манифеста файлов.' }
        $manifest = Read-ZipText $manifestEntry | ConvertFrom-Json
        $properties = @($manifest.PSObject.Properties)
        if ($properties.Count + 1 -ne $entries.Count) { throw 'Файлы Release не совпадают с манифестом.' }
        foreach ($required in @('server/server.js','server/package.json','launcher/localbox_launcher.py','version.json')) {
            if ($properties.Name -cnotcontains $required) { throw "Неполный Release: $required" }
        }
        foreach ($property in $properties) {
            if ($property.Name -eq 'installer/payload-sha256.json' -or -not (Test-PayloadPath $property.Name) -or
                $property.Value -cnotmatch '^[a-f0-9]{64}$') { throw 'Некорректный манифест Release.' }
            $entry = $package.GetEntry($property.Name)
            if (-not $entry) { throw "Нет файла Release: $($property.Name)" }
            $stream = $entry.Open()
            $sha = [Security.Cryptography.SHA256]::Create()
            try { $actual = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
            finally { $sha.Dispose(); $stream.Dispose() }
            if ($actual -cne $property.Value) { throw "Повреждён файл Release: $($property.Name)" }
        }
        $actualVersion = (Read-ZipText ($package.GetEntry('version.json')) | ConvertFrom-Json).version
        if ((Get-ReleaseVersion $actualVersion) -ne (Get-ReleaseVersion $Version)) { throw 'Версия архива не совпадает с тегом Release.' }
        New-Item -ItemType Directory -Force -Path $Payload | Out-Null
        foreach ($entry in $entries) {
            $file = Join-Path $Payload $entry.FullName
            New-Item -ItemType Directory -Force -Path (Split-Path $file -Parent) | Out-Null
            $input = $entry.Open()
            $output = [IO.File]::Create($file)
            try { $input.CopyTo($output) }
            finally { $output.Dispose(); $input.Dispose() }
        }
    } finally { $package.Dispose() }
}

function Get-LatestPayload([string]$Work) {
    if ((Test-Path -LiteralPath $Work) -and (Get-ChildItem -LiteralPath $Work -Force | Select-Object -First 1)) {
        throw 'Папка загрузки Release должна быть пустой.'
    }
    Write-Host 'Проверяю последний стабильный Release LocalBox…'
    try { $release = Read-ReleaseText "https://api.github.com/repos/$script:LocalBoxRepository/releases/latest" }
    catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) { throw 'Нет опубликованного стабильного Release LocalBox.' }
        throw
    }
    if (-not $release.tag_name -or $release.draft -or $release.prerelease) { throw 'Нет опубликованного стабильного Release LocalBox.' }
    [void](Get-ReleaseVersion $release.tag_name)
    $asset = @($release.assets | Where-Object { $_.name -ceq 'localbox-update.zip' })
    if ($asset.Count -ne 1) { throw "В выпуске $($release.tag_name) нет localbox-update.zip. Автору нужно прикрепить архив к Release." }
    $asset = $asset[0]
    $expected = ''
    if ($asset.digest -match '^sha256:([a-fA-F0-9]{64})$') { $expected = $matches[1] }
    else {
        $checksums = @($release.assets | Where-Object { $_.name -ceq 'SHA256SUMS' })
        if ($checksums.Count -ne 1) { throw 'В Release нет SHA-256 для проверки архива.' }
        $text = [string](Read-ReleaseText (Get-ReleaseAssetUrl $checksums[0]))
        if ($text.Length -gt 65536) { throw 'Слишком большой список SHA256SUMS.' }
        $found = [regex]::Matches($text, '(?m)^([a-fA-F0-9]{64})\s+\*?localbox-update\.zip\s*$')
        if ($found.Count -ne 1) { throw 'В SHA256SUMS отсутствует однозначная сумма архива.' }
        $expected = $found[0].Groups[1].Value
    }
    New-Item -ItemType Directory -Force -Path $Work | Out-Null
    $archive = Join-Path $Work 'localbox-update.zip'
    $payload = Join-Path $Work 'payload'
    try {
        Write-Host "Скачиваю Release $($release.tag_name)…"
        Save-ReleaseArchive (Get-ReleaseAssetUrl $asset) $archive
        if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expected) { throw 'SHA-256 Release не совпала. Папка установки не изменена.' }
        Expand-VerifiedRelease $archive $payload $release.tag_name
        $env:LOCALBOX_RELEASE_TAG = [string]$release.tag_name
        Write-Host "Устанавливаю Release $($release.tag_name)."
        return $payload
    } catch {
        if (Test-Path -LiteralPath $payload) { Remove-Item -LiteralPath $payload -Recurse -Force }
        throw
    } finally {
        if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
    }
}

function Copy-VerifiedPayload([string]$Source, [string]$Destination) {
    $manifestPath = Join-Path $Source 'installer/payload-sha256.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'Не найден манифест установки. Запустите собранный setup.exe.' }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($property in $manifest.PSObject.Properties) {
        if (-not (Test-PayloadPath $property.Name)) { throw "Недопустимый файл установки: $($property.Name)" }
        $file = Join-Path $Source $property.Name
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $property.Value) { throw "Не совпала контрольная сумма: $($property.Name)" }
        $to = Join-Path $Destination $property.Name
        $current = $to
        while ($current -and $current.Length -gt $Destination.Length) {
            if (Test-Path -LiteralPath $current) {
                $item = Get-Item -LiteralPath $current -Force
                if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Путь установки содержит ссылку: $current" }
            }
            $current = Split-Path $current -Parent
        }
    }
    if ([IO.Path]::GetFullPath($Source) -eq [IO.Path]::GetFullPath($Destination)) { return }
    foreach ($property in $manifest.PSObject.Properties) {
        $to = Join-Path $Destination $property.Name
        New-Item -ItemType Directory -Force -Path (Split-Path $to -Parent) | Out-Null
        Copy-Item -LiteralPath (Join-Path $Source $property.Name) -Destination $to -Force
    }
}
