# Shared with Python: keep user-facing text in one UTF-8 catalogue.
if (-not (Get-Variable LocalBoxTranslations -Scope Script -ErrorAction SilentlyContinue)) {
    $catalogPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'launcher/setup/translations/en.json'
    $script:LocalBoxTranslations = Get-Content -LiteralPath $catalogPath -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Set-LocalBoxLanguage([string]$Language) {
    if ($Language -notin @('ru', 'en')) {
        $Language = if ($env:LOCALBOX_LANGUAGE -in @('ru', 'en')) { $env:LOCALBOX_LANGUAGE }
                    elseif ([Globalization.CultureInfo]::CurrentUICulture.TwoLetterISOLanguageName -eq 'ru') { 'ru' }
                    else { 'en' }
    }
    $env:LOCALBOX_LANGUAGE = $Language
}

function T([string]$Message, [object[]]$Values = @()) {
    $text = $Message
    if ($env:LOCALBOX_LANGUAGE -eq 'en') {
        $translation = $script:LocalBoxTranslations.PSObject.Properties[$Message]
        if ($null -ne $translation) { $text = [string]$translation.Value }
    }
    if ($Values.Count -gt 0) { return [string]::Format([Globalization.CultureInfo]::CurrentCulture, $text, $Values) }
    return $text
}

Set-LocalBoxLanguage $env:LOCALBOX_LANGUAGE

# A UTF-8 console (chcp 65001) cannot draw Cyrillic with the legacy raster font: the text turns into
# garbage. Switch only that window to Consolas; Windows Terminal and TrueType consoles stay as they are.
function Use-LocalBoxConsoleFont {
    if ($env:OS -ne 'Windows_NT') { return }
    try {
        if ([Console]::IsOutputRedirected) { return }
        if (-not ('LocalBoxConsoleFont' -as [type])) {
            Add-Type -ErrorAction Stop @'
using System;
using System.Runtime.InteropServices;
public static class LocalBoxConsoleFont {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct Info {
        public uint Size; public uint Index; public short Width; public short Height; public int Family; public int Weight;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string Face;
    }
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr GetStdHandle(int handle);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)] static extern bool GetCurrentConsoleFontEx(IntPtr output, bool maximum, ref Info info);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)] static extern bool SetCurrentConsoleFontEx(IntPtr output, bool maximum, ref Info info);
    public static bool UseTrueType() {
        IntPtr output = GetStdHandle(-11);
        Info info = new Info(); info.Size = (uint)Marshal.SizeOf(typeof(Info));
        if (!GetCurrentConsoleFontEx(output, false, ref info) || (info.Family & 4) != 0) return false; // 4 = TMPF_TRUETYPE
        Info next = new Info(); next.Size = info.Size; next.Height = info.Height < 14 ? (short)16 : info.Height;
        next.Family = 54; next.Weight = 400; next.Face = "Consolas";
        return SetCurrentConsoleFontEx(output, false, ref next);
    }
}
'@
        }
        [void][LocalBoxConsoleFont]::UseTrueType()
    } catch { }
}

