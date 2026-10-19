# PowerShell 5.1: reuse working dependencies from the runtime, PATH and known install locations.
function Invoke-ToolProbe([string]$File, [string[]]$Arguments) {
    # Windows PowerShell turns native stderr into ErrorRecords. A failed probe is
    # an expected result, not a terminating error in the installer's transcript.
    $ErrorActionPreference = 'SilentlyContinue'
    $PSNativeCommandUseErrorActionPreference = $false
    $global:LASTEXITCODE = -1
    try {
        $output = @(& $File @Arguments 2>$null)
        if ($global:LASTEXITCODE -eq 0) { return @{text=($output -join "`n")} }
    } catch { }
    return $null
}

function Find-WorkingTool([string]$Name, [object[]]$Candidates, [string[]]$Arguments = @('--version')) {
    $all = @($Candidates)
    $all += @(Get-Command $Name -CommandType Application -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
    foreach ($file in @($all | Where-Object { $_ } | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { continue }
        if (Invoke-ToolProbe $file $Arguments) { return [string]$file }
    }
    return $null
}

function Find-Python {
    $candidates = @($previous.python, (Join-Path $runtime 'python\python.exe'))
    $launcher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue
    if ($launcher) {
        try { $candidates += & $launcher.Source -3 -c 'import sys; print(sys.executable)' 2>$null } catch { }
    }
    foreach ($base in @('HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore', 'HKLM:\Software\WOW6432Node\Python\PythonCore')) {
        foreach ($version in @(Get-ChildItem -LiteralPath $base -ErrorAction SilentlyContinue)) {
            $item = Get-ItemProperty ($version.PSPath + '\InstallPath') -ErrorAction SilentlyContinue
            if ($item.'(default)') { $candidates += Join-Path $item.'(default)' 'python.exe' }
        }
    }
    foreach ($base in @($env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $base) { continue }
        $candidates += @(Get-ChildItem -Path (Join-Path $base 'Programs\Python\Python*\python.exe'), (Join-Path $base 'Python*\python.exe') -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    }
    $check = @('-c', 'import sys,tkinter,venv,ensurepip; assert (3,10) <= sys.version_info and sys.maxsize > 2**32')
    $python = Find-WorkingTool 'python.exe' $candidates $check
    if (-not $python) { $python = Find-WorkingTool 'python3.exe' @() $check }
    return $python
}

function Get-NodeTools([string]$Node) {
    if (-not (Test-Path -LiteralPath $Node -PathType Leaf)) { return $null }
    $probe = Invoke-ToolProbe $Node @('--version')
    if (-not $probe -or $probe.text.Trim() -notmatch '^v([0-9]+)\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$') { return $null }
    if ([int]$matches[1] -lt 18) { return $null }
    $directory = Split-Path $Node -Parent
    $npmRoot = Join-Path $directory 'node_modules\npm'
    $cli = Join-Path $npmRoot 'bin\npm-cli.js'
    if (-not (Test-Path -LiteralPath $cli -PathType Leaf)) { return $null }
    if (-not (Invoke-ToolProbe $Node @($cli, '--version'))) { return $null }
    if (-not (Invoke-ToolProbe $Node @((Join-Path $PSScriptRoot 'check-npm.js'), $npmRoot))) {
        Write-Host "npm не проходит проверку модулей установки: $npmRoot"
        return $null
    }
    $npm = Join-Path $directory 'npm.cmd'
    if (-not (Test-Path -LiteralPath $npm -PathType Leaf)) { $npm = $cli }
    return @{node=$Node; npm=$npm; npm_cli=$cli}
}

function Find-Node {
    $candidates = @($previous.node, (Join-Path $runtime 'node\node.exe'))
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
        if ($base) { $candidates += Join-Path $base 'nodejs\node.exe' }
    }
    foreach ($base in @($env:NVM_SYMLINK, $env:VOLTA_HOME)) {
        if ($base) { $candidates += Join-Path $base 'node.exe'; $candidates += Join-Path $base 'bin\node.exe' }
    }
    foreach ($base in @($env:NVM_HOME, $env:FNM_DIR, $env:MISE_DATA_DIR)) {
        if ($base) {
            $candidates += @(Get-ChildItem -Path (Join-Path $base 'v*\node.exe'),
                (Join-Path $base 'node-versions\v*\installation\node.exe'),
                (Join-Path $base 'installs\node\*\node.exe') -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
        }
    }
    # MSI updates the machine/user PATH; the running setup retains its old environment.
    foreach ($scope in @('Machine', 'User')) {
        foreach ($directory in ([Environment]::GetEnvironmentVariable('Path', $scope) -split ';')) {
            if ($directory) { $candidates += Join-Path ([Environment]::ExpandEnvironmentVariables($directory.Trim('"'))) 'node.exe' }
        }
    }
    foreach ($key in @('HKLM:\SOFTWARE\Node.js', 'HKCU:\SOFTWARE\Node.js')) {
        $item = Get-ItemProperty $key -ErrorAction SilentlyContinue
        if ($item.InstallPath) { $candidates += Join-Path $item.InstallPath 'node.exe' }
    }
    $candidates += @(Get-Command node.exe -CommandType Application -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
    foreach ($candidate in @($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        $tools = Get-NodeTools ([string]$candidate)
        if ($tools) { return $tools }
    }
    return $null
}
