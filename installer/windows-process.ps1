# PowerShell 5.1: keep the real Process handle and copy UTF-8 logs without a native pipeline.
function ConvertTo-LocalBoxArgument([AllowEmptyString()][string]$Value) {
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Start-LocalBoxProcess {
    param([string]$File, [string[]]$Arguments, [string]$Stdout = '', [string]$Stderr = '')
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $File
    $info.Arguments = (($Arguments | ForEach-Object { ConvertTo-LocalBoxArgument $_ }) -join ' ')
    $info.UseShellExecute = $false
    $capture = [bool]$Stdout
    $info.CreateNoWindow = $capture
    $info.RedirectStandardOutput = $capture
    $info.RedirectStandardError = $capture
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $info
    $worker = [pscustomobject]@{ Process = $process; Streams = @(); Copies = @() }
    try {
        if ($capture) {
            foreach ($path in @($Stdout, $Stderr)) {
                $worker.Streams += [IO.FileStream]::new($path, [IO.FileMode]::Create,
                    [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite, 1, $true)
            }
        }
        if (-not $process.Start()) { throw "Не удалось запустить $File" }
        # Start-Process -PassThru with redirection can lose ExitCode on Windows.
        # Process.Start plus retaining the handle also covers an immediately exiting child.
        [void]$process.Handle
        if ($capture) {
            $worker.Copies += $process.StandardOutput.BaseStream.CopyToAsync($worker.Streams[0])
            $worker.Copies += $process.StandardError.BaseStream.CopyToAsync($worker.Streams[1])
        }
        return $worker
    } catch {
        foreach ($stream in $worker.Streams) { $stream.Dispose() }
        $process.Dispose()
        throw
    }
}

function Complete-LocalBoxProcess($Worker) {
    try {
        $Worker.Process.WaitForExit()
        foreach ($copy in $Worker.Copies) { [void]$copy.GetAwaiter().GetResult() }
        $code = $Worker.Process.ExitCode
        if ($null -eq $code) { throw 'Не удалось получить код завершения установки.' }
        return [int]$code
    } finally {
        foreach ($stream in $Worker.Streams) { $stream.Dispose() }
        $Worker.Process.Dispose()
    }
}
