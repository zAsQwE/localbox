# Background setup worker: resolve the Release before touching the installation.
param([string]$Source, [string]$Root, [string]$OptionsFile, [switch]$Latest)
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Text.UTF8Encoding]::new($false)
try { [Console]::InputEncoding = $OutputEncoding } catch { }
try { [Console]::OutputEncoding = $OutputEncoding } catch { }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Source = [IO.Path]::GetFullPath($Source)
$Root = [IO.Path]::GetFullPath($Root)
$work = Join-Path ([IO.Path]::GetTempPath()) ('localbox-release-setup-' + [guid]::NewGuid().ToString('N'))
. (Join-Path $PSScriptRoot 'windows-release.ps1')
try {
    if ($Latest) { $Source = Get-LatestPayload $work }
    Copy-VerifiedPayload $Source $Root
    & (Join-Path $Root 'installer/windows-bootstrap.ps1') -Root $Root -OptionsFile $OptionsFile
    exit $LASTEXITCODE
} catch {
    Write-Host "Установка не завершена: $_"
    exit 1
} finally {
    if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force }
}
