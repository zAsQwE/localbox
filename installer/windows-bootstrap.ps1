# Windows 10/11 x64, PowerShell 5.1. Общий код для setup.exe и install.bat.
param([string]$Root = '', [string]$OptionsFile = '', [switch]$Prompt)
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Text.UTF8Encoding]::new($false)
try { [Console]::InputEncoding = $OutputEncoding } catch { }
try { [Console]::OutputEncoding = $OutputEncoding } catch { }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
if (-not $Root) { $Root = Split-Path $PSScriptRoot -Parent }
$Root = [IO.Path]::GetFullPath($Root)
$options = @{runtime = (Join-Path $Root 'runtime'); tts = 'piper'; voices = 'ru_RU-denis-medium'; game = ''; cheat_content = $null; dodo = '0'; russian = '0'}
if ($OptionsFile) {
    foreach ($line in Get-Content -LiteralPath $OptionsFile) {
        if ($line -match '^([^;\[=]+)=(.*)$') { $options[$matches[1].Trim()] = $matches[2] }
    }
}
if ($Prompt) {
    Write-Host 'LocalBox — установка в текущую папку. Для выбора папки приложения используйте setup.exe.'
    $answer = Read-Host "Папка зависимостей [$($options.runtime)]"
    if ($answer) { $options.runtime = $answer }
    do { $answer = Read-Host 'TTS: 1 Piper, 2 Silero, 3 Оба, 4 Без озвучки [1]' } while ($answer -and $answer -notin @('1', '2', '3', '4'))
    if (-not $answer) { $answer = '1' }
    $options.tts = @('piper', 'silero', 'both', 'none')[[int]$answer - 1]
    if ($options.tts -in @('piper', 'both')) {
        do { $answer = Read-Host 'Piper: 1 Денис, 2 Дмитрий, 3 Ирина, 4 Руслан. Номера через запятую [1]' } while ($answer -and $answer -notmatch '^[1-4](,[1-4])*$')
        if (-not $answer) { $answer = '1' }
        $catalog = @('ru_RU-denis-medium', 'ru_RU-dmitri-medium', 'ru_RU-irina-medium', 'ru_RU-ruslan-medium')
        $options.voices = (($answer.Split(',') | ForEach-Object { $catalog[[int]$_ - 1] }) -join ',')
    }
    $options.game = Read-Host 'Папка Jackbox Party Pack 10 (Enter — без поддержки Додо Ре Ми)'
    if ($options.game) { $options.dodo = '1' }
    $options.cheat_content = Read-Host 'Папка с играми для читов (Enter — поиск в Steam)'
}
if (-not $options.runtime) { $options.runtime = Join-Path $Root 'runtime' }
$runtime = [IO.Path]::GetFullPath($options.runtime)
$cache = Join-Path $runtime 'downloads'
New-Item -ItemType Directory -Force -Path $cache | Out-Null
$logfile = Join-Path $Root 'install.log'

function Download-File([string]$Url, [string]$File, [string]$Hash = '') {
    if ((Test-Path -LiteralPath $File) -and $Hash -and ((Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash -eq $Hash)) { return }
    Write-Host "Загрузка: $Url"
    $temporary = "$File.part"
    try {
        $client = New-Object Net.WebClient
        $client.Headers.Add('User-Agent', 'LocalBox-Setup')
        $client.DownloadFile($Url, $temporary)
        if ((Get-Item -LiteralPath $temporary).Length -eq 0) { throw "Скачан пустой файл: $Url" }
        if ($Hash -and ((Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash -ne $Hash)) { throw "Не совпала SHA-256: $Url" }
        Move-Item -LiteralPath $temporary -Destination $File -Force
    } finally {
        if ($client) { $client.Dispose() }
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
    }
}

function Run-SignedInstaller([string]$File, [string]$Arguments, [bool]$Elevate = $false) {
    $signature = Get-AuthenticodeSignature -LiteralPath $File
    if ($signature.Status -ne 'Valid') { throw "Не удалось проверить цифровую подпись $File" }
    if ($Elevate) { $process = Start-Process -FilePath $File -ArgumentList $Arguments -Verb RunAs -Wait -PassThru }
    else { $process = Start-Process -FilePath $File -ArgumentList $Arguments -Wait -PassThru }
    if ($process.ExitCode -notin @(0, 3010, 1641, 1638)) { throw "Установщик $File завершился с кодом $($process.ExitCode)" }
}

$previous = @{}
$pathsFile = Join-Path $Root 'launcher\install-paths.json'
if (Test-Path -LiteralPath $pathsFile) {
    $saved = Get-Content -LiteralPath $pathsFile -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($property in $saved.PSObject.Properties) { $previous[$property.Name] = $property.Value }
}
. (Join-Path $PSScriptRoot 'windows-discovery.ps1')
. (Join-Path $PSScriptRoot 'windows-node.ps1')

try {
    Start-Transcript -Path $logfile -Append | Out-Null
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Нужна 64-битная Windows 10 или 11.' }
    Write-Host "Приложение: $Root"
    Write-Host "Зависимости: $runtime"
    if ($options.game) {
        $game = [IO.Path]::GetFullPath($options.game)
        $foundSongs = $false
        foreach ($candidate in @((Join-Path $game 'games\NopusOpus\songs'), (Join-Path $game 'NopusOpus\songs'), (Join-Path $game 'songs'), $game)) {
            if (Test-Path -LiteralPath $candidate -PathType Container) {
                foreach ($folder in Get-ChildItem -LiteralPath $candidate -Directory) {
                    if (Get-ChildItem -LiteralPath $folder.FullName -Filter 'backing*.ogg' -File) { $foundSongs = $true; break }
                }
            }
            if ($foundSongs) { break }
        }
        if (-not $foundSongs) { throw 'В указанной папке Jackbox 10 не найдена музыка games\NopusOpus\songs\<песня>\backing*.ogg.' }
    }
    $python = Find-Python
    if (-not $python) {
        $pythonInstaller = Join-Path $cache 'python-3.12.10-amd64.exe'
        Download-File 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' $pythonInstaller
        $pythonTarget = Join-Path $runtime 'python'
        Run-SignedInstaller $pythonInstaller "/quiet InstallAllUsers=0 TargetDir=`"$pythonTarget`" Include_launcher=0 Include_test=0 Include_doc=0 Include_tcltk=1 Include_pip=1 Shortcuts=0 PrependPath=0"
        $python = Find-Python
        if (-not $python) { throw 'Python с tkinter не найден после установки.' }
    }
    Write-Host "Python: $python"
    $nodeTools = Ensure-Node
    Write-Host "Использую Node.js: $($nodeTools.node)"
    $ffmpeg = Find-WorkingTool 'ffmpeg.exe' @($previous.ffmpeg, (Join-Path $runtime 'ffmpeg\bin\ffmpeg.exe')) @('-version')
    if (-not $ffmpeg) {
        $hashText = Invoke-RestMethod 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256'
        $hash = [regex]::Match($hashText, '[a-fA-F0-9]{64}').Value
        if (-not $hash) { throw 'Не найдена SHA-256 ffmpeg.' }
        $archive = Join-Path $cache 'ffmpeg.zip'
        Download-File 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' $archive $hash
        $stage = Join-Path $cache 'ffmpeg-extracted'
        Expand-Archive -LiteralPath $archive -DestinationPath $stage -Force
        $exe = Get-ChildItem -LiteralPath $stage -Filter ffmpeg.exe -Recurse | Select-Object -First 1
        if (-not $exe) { throw 'ffmpeg.exe отсутствует в архиве.' }
        New-Item -ItemType Directory -Force -Path (Join-Path $runtime 'ffmpeg') | Out-Null
        Copy-Item -Path (Join-Path $exe.Directory.Parent.FullName '*') -Destination (Join-Path $runtime 'ffmpeg') -Recurse -Force
        $ffmpeg = Join-Path $runtime 'ffmpeg\bin\ffmpeg.exe'
    }
    $gitCandidates = @($previous.git, (Join-Path $runtime 'git\cmd\git.exe'))
    foreach ($base in @($env:ProgramFiles, $env:LOCALAPPDATA)) {
        if ($base) { $gitCandidates += Join-Path $base 'Git\cmd\git.exe'; $gitCandidates += Join-Path $base 'Programs\Git\cmd\git.exe' }
    }
    $git = Find-WorkingTool 'git.exe' $gitCandidates
    if (-not $git) {
        $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/git-for-windows/git/releases/latest' -Headers @{'User-Agent' = 'LocalBox-Setup'}
        $asset = $release.assets | Where-Object { $_.name -match '^MinGit-[0-9.]+-64-bit.zip$' } | Select-Object -First 1
        if (-not $asset -or $asset.digest -notmatch '^sha256:([a-fA-F0-9]{64})$') { throw 'Не найдена официальная сборка MinGit с SHA-256.' }
        $hash = $matches[1]
        $archive = Join-Path $cache $asset.name
        Download-File $asset.browser_download_url $archive $hash
        Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $runtime 'git') -Force
        $git = Join-Path $runtime 'git\cmd\git.exe'
    }
    # MinGit не включает openssl.exe; mkcert создаёт локальные TLS-сертификаты без установки CA.
    $openssl = Find-WorkingTool 'openssl.exe' @($previous.openssl, (Join-Path (Split-Path (Split-Path $git -Parent) -Parent) 'usr\bin\openssl.exe')) @('version')
    $mkcert = Find-WorkingTool 'mkcert.exe' @($previous.mkcert, (Join-Path $runtime 'bin\mkcert.exe')) @('-version')
    if (-not $openssl -and -not $mkcert) {
        $mkcert = Join-Path $runtime 'bin\mkcert.exe'
        New-Item -ItemType Directory -Force -Path (Split-Path $mkcert -Parent) | Out-Null
        Download-File 'https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-windows-amd64.exe' $mkcert
    }
    if ($mkcert) {
        & $mkcert -version
        if ($LASTEXITCODE -ne 0) { throw 'Не запускается mkcert.' }
    }
    if ($options.tts -in @('piper', 'both')) {
        $system64 = "$env:SystemRoot\System32"
        if (-not [Environment]::Is64BitProcess) { $system64 = "$env:SystemRoot\Sysnative" }
        if (-not (Test-Path -LiteralPath "$system64\vcruntime140_1.dll")) {
            $vc = Join-Path $cache 'vc_redist.x64.exe'
            Download-File 'https://aka.ms/vs/17/release/vc_redist.x64.exe' $vc
            Run-SignedInstaller $vc '/install /quiet /norestart' $true
        }
    }
    $env:PATH = "$runtime\bin;$runtime\node;$runtime\git\cmd;$runtime\git\ucrt64\bin;$runtime\git\mingw64\bin;$runtime\ffmpeg\bin;$env:PATH"
    foreach ($tool in @($nodeTools.node, $nodeTools.npm, $git, $ffmpeg, $openssl, $mkcert)) {
        if ($tool) { $env:PATH = (Split-Path $tool -Parent) + ';' + $env:PATH }
    }
    $manifest = Join-Path $Root 'launcher\install-paths.json'
    $previous.runtime = $runtime; $previous.python = $python
    $previous.node = $nodeTools.node; $previous.npm = $nodeTools.npm
    $previous.npm_cli = $nodeTools.npm_cli
    $previous.git = $git; $previous.ffmpeg = $ffmpeg
    $previous.openssl = $openssl; $previous.mkcert = $mkcert
    $previous | ConvertTo-Json | Set-Content -LiteralPath $manifest -Encoding UTF8
    $installArgs = @((Join-Path $Root 'installer\install.py'), '--target', $Root, '--runtime', $runtime,
                         '--tts', $options.tts, '--voices', $options.voices, '--skip-system-deps')
        if ($null -ne $options.cheat_content) { $installArgs += ('--cheat-content=' + $options.cheat_content) }
        if ($options.game) { $installArgs += @('--game', $options.game) }
        if ($options.dodo -eq '1') { $installArgs += '--dodo' }
        if ($options.russian -eq '1') { $installArgs += '--ru' }
    & $python @installArgs
    $status = $LASTEXITCODE
    if ($status -ne 0) { throw "Установка не завершена (код $status). Журнал: $logfile" }
    Write-Host 'LocalBox установлен. Запуск: start-server.bat'
    Stop-Transcript | Out-Null
    exit 0
} catch {
    Write-Host "Установка не завершена: $_"
    Write-Host "Журнал: $logfile"
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}
