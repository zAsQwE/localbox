# PowerShell 5.1: reuse working dependencies from the runtime, PATH and known install locations.
function Find-WorkingTool([string]$Name, [object[]]$Candidates, [string[]]$Arguments = @('--version')) {
    $all = @($Candidates)
    $all += @(Get-Command $Name -CommandType Application -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
    foreach ($file in @($all | Where-Object { $_ } | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { continue }
        try {
            $output = & $file @Arguments 2>$null
            if ($LASTEXITCODE -eq 0) { return [string]$file }
        } catch { }
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

function Find-Node {
    $candidates = @($previous.node, (Join-Path $runtime 'node\node.exe'))
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
        if ($base) { $candidates += Join-Path $base 'nodejs\node.exe' }
    }
    foreach ($base in @($env:NVM_SYMLINK, $env:VOLTA_HOME)) {
        if ($base) { $candidates += Join-Path $base 'node.exe'; $candidates += Join-Path $base 'bin\node.exe' }
    }
    foreach ($key in @('HKLM:\SOFTWARE\Node.js', 'HKCU:\SOFTWARE\Node.js')) {
        $item = Get-ItemProperty $key -ErrorAction SilentlyContinue
        if ($item.InstallPath) { $candidates += Join-Path $item.InstallPath 'node.exe' }
    }
    $candidates += @(Get-Command node.exe -CommandType Application -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
    foreach ($candidate in @($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        $node = Find-WorkingTool '__localbox_node_probe__' @($candidate) @('-e', 'process.exit(Number(process.versions.node.split(".")[0]) < 18 ? 1 : 0)')
        if (-not $node) { continue }
        $oldPath = $env:PATH
        try {
            $env:PATH = (Split-Path $node -Parent) + ';' + $oldPath
            $npm = Find-WorkingTool 'npm.cmd' @((Join-Path (Split-Path $node -Parent) 'npm.cmd'))
            if ($npm) { return @{node=$node; npm=$npm} }
        } finally { $env:PATH = $oldPath }
    }
    return $null
}
