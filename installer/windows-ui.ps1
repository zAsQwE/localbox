# Windows 10/11: download settings, no wizard pages and no Python prerequisite.
param([string]$Source = '')
$ErrorActionPreference = 'Stop'
if (-not $Source) { $Source = Split-Path $PSScriptRoot -Parent }
$Source = [IO.Path]::GetFullPath($Source)
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Windows.Forms
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class LocalBoxWindowTheme {
    [DllImport("dwmapi.dll")]
    public static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);
}
'@

[xml]$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" Title="LocalBox"
        Width="680" Height="680" MinWidth="620" MinHeight="580" WindowStartupLocation="CenterScreen"
        FontFamily="Segoe UI" FontSize="14" Background="{DynamicResource Bg}" Foreground="{DynamicResource Fg}">
  <Window.Resources>
    <SolidColorBrush x:Key="Bg" Color="#F5F5F5"/>
    <SolidColorBrush x:Key="Field" Color="#FFFFFF"/>
    <SolidColorBrush x:Key="Fg" Color="#202124"/>
    <SolidColorBrush x:Key="Muted" Color="#626872"/>
    <SolidColorBrush x:Key="Border" Color="#C7CCD3"/>
    <SolidColorBrush x:Key="Hover" Color="#E6E9EF"/>
    <SolidColorBrush x:Key="Accent" Color="#2867C8"/>
    <SolidColorBrush x:Key="OnAccent" Color="#FFFFFF"/>
    <SolidColorBrush x:Key="Error" Color="#B3261E"/>
    <SolidColorBrush x:Key="Success" Color="#267139"/>
    <Style TargetType="Button">
      <Setter Property="Background" Value="{DynamicResource Field}"/>
      <Setter Property="Foreground" Value="{DynamicResource Fg}"/>
      <Setter Property="BorderBrush" Value="{DynamicResource Border}"/>
      <Setter Property="BorderThickness" Value="1"/>
      <Setter Property="Padding" Value="14,7"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Face" Background="{TemplateBinding Background}" BorderBrush="{TemplateBinding BorderBrush}" BorderThickness="{TemplateBinding BorderThickness}" CornerRadius="3">
              <ContentPresenter Margin="{TemplateBinding Padding}" HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="Face" Property="Opacity" Value="0.85"/></Trigger>
              <Trigger Property="IsKeyboardFocused" Value="True"><Setter TargetName="Face" Property="BorderBrush" Value="{DynamicResource Accent}"/></Trigger>
              <Trigger Property="IsEnabled" Value="False"><Setter TargetName="Face" Property="Opacity" Value="0.5"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="TextBox">
      <Setter Property="Background" Value="{DynamicResource Field}"/>
      <Setter Property="Foreground" Value="{DynamicResource Fg}"/>
      <Setter Property="CaretBrush" Value="{DynamicResource Fg}"/>
      <Setter Property="BorderBrush" Value="{DynamicResource Border}"/>
      <Setter Property="Padding" Value="8,7"/>
      <Setter Property="Template"><Setter.Value>
        <ControlTemplate TargetType="TextBox">
          <Border x:Name="Face" Background="{TemplateBinding Background}" BorderBrush="{TemplateBinding BorderBrush}" BorderThickness="1" CornerRadius="3">
            <ScrollViewer x:Name="PART_ContentHost" Margin="{TemplateBinding Padding}"/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsKeyboardFocusWithin" Value="True"><Setter TargetName="Face" Property="BorderBrush" Value="{DynamicResource Accent}"/></Trigger>
            <Trigger Property="IsEnabled" Value="False"><Setter TargetName="Face" Property="Opacity" Value="0.5"/></Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value></Setter>
    </Style>
    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="{DynamicResource Fg}"/>
      <Setter Property="Margin" Value="0,4,18,4"/>
      <Setter Property="Template"><Setter.Value>
        <ControlTemplate TargetType="CheckBox">
          <StackPanel Orientation="Horizontal">
            <Border x:Name="Box" Width="17" Height="17" VerticalAlignment="Center" Background="{DynamicResource Field}" BorderBrush="{DynamicResource Border}" BorderThickness="1" CornerRadius="2">
              <TextBlock x:Name="Tick" Text="✓" Visibility="Collapsed" Foreground="{DynamicResource OnAccent}" FontSize="13" HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ContentPresenter Margin="8,0,0,0" VerticalAlignment="Center"/>
          </StackPanel>
          <ControlTemplate.Triggers>
            <Trigger Property="IsChecked" Value="True"><Setter TargetName="Tick" Property="Visibility" Value="Visible"/><Setter TargetName="Box" Property="Background" Value="{DynamicResource Accent}"/></Trigger>
            <Trigger Property="IsKeyboardFocused" Value="True"><Setter TargetName="Box" Property="BorderBrush" Value="{DynamicResource Accent}"/></Trigger>
            <Trigger Property="IsEnabled" Value="False"><Setter Property="Opacity" Value="0.5"/></Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value></Setter>
    </Style>
    <Style TargetType="ComboBoxItem">
      <Setter Property="Foreground" Value="{DynamicResource Fg}"/>
      <Setter Property="Background" Value="{DynamicResource Field}"/>
      <Setter Property="Padding" Value="8"/>
      <Setter Property="Template"><Setter.Value>
        <ControlTemplate TargetType="ComboBoxItem">
          <Border x:Name="Face" Background="{TemplateBinding Background}" Padding="{TemplateBinding Padding}"><ContentPresenter/></Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsHighlighted" Value="True"><Setter TargetName="Face" Property="Background" Value="{DynamicResource Hover}"/></Trigger>
            <Trigger Property="IsSelected" Value="True"><Setter TargetName="Face" Property="Background" Value="{DynamicResource Accent}"/><Setter Property="Foreground" Value="{DynamicResource OnAccent}"/></Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value></Setter>
    </Style>
    <Style TargetType="ComboBox">
      <Setter Property="Foreground" Value="{DynamicResource Fg}"/>
      <Setter Property="Template"><Setter.Value>
        <ControlTemplate TargetType="ComboBox">
          <Grid>
            <ToggleButton Focusable="False" IsChecked="{Binding IsDropDownOpen, Mode=TwoWay, RelativeSource={RelativeSource TemplatedParent}}">
              <ToggleButton.Template><ControlTemplate TargetType="ToggleButton">
                <Border Background="{DynamicResource Field}" BorderBrush="{DynamicResource Border}" BorderThickness="1" CornerRadius="3">
                  <TextBlock Text="▾" Foreground="{DynamicResource Fg}" HorizontalAlignment="Right" Margin="0,0,10,0" VerticalAlignment="Center"/>
                </Border>
              </ControlTemplate></ToggleButton.Template>
            </ToggleButton>
            <ContentPresenter IsHitTestVisible="False" Content="{TemplateBinding SelectionBoxItem}" Margin="8,8,30,8" VerticalAlignment="Center"/>
            <Popup x:Name="PART_Popup" IsOpen="{TemplateBinding IsDropDownOpen}" Placement="Bottom" AllowsTransparency="True" Focusable="False">
              <Border Background="{DynamicResource Field}" BorderBrush="{DynamicResource Border}" BorderThickness="1" MinWidth="{Binding ActualWidth, RelativeSource={RelativeSource TemplatedParent}}">
                <ScrollViewer MaxHeight="250"><ItemsPresenter KeyboardNavigation.DirectionalNavigation="Contained"/></ScrollViewer>
              </Border>
            </Popup>
          </Grid>
          <ControlTemplate.Triggers><Trigger Property="IsEnabled" Value="False"><Setter Property="Opacity" Value="0.5"/></Trigger></ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value></Setter>
    </Style>
  </Window.Resources>
  <Grid Margin="24,18">
    <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
    <TextBlock Text="LocalBox" FontSize="28" FontWeight="SemiBold" Margin="0,0,0,16"/>
    <ScrollViewer Grid.Row="1" VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Disabled">
      <StackPanel x:Name="Settings">
        <TextBlock Text="Куда скачать LocalBox" Margin="0,0,0,6"/>
        <DockPanel><Button x:Name="AppBrowse" Content="Обзор…" DockPanel.Dock="Right" Margin="8,0,0,0"/><TextBox x:Name="AppPath"/></DockPanel>
        <TextBlock Text="Папка зависимостей и TTS" Margin="0,12,0,6"/>
        <DockPanel><Button x:Name="RuntimeBrowse" Content="Обзор…" DockPanel.Dock="Right" Margin="8,0,0,0"/><TextBox x:Name="RuntimePath"/></DockPanel>
        <TextBlock Text="Озвучка" FontWeight="SemiBold" Margin="0,20,0,7"/>
        <ComboBox x:Name="Tts" SelectedIndex="0">
          <ComboBoxItem Content="Piper — нейроголоса" Tag="piper"/><ComboBoxItem Content="Silero — русские нейроголоса" Tag="silero"/>
          <ComboBoxItem Content="Piper + Silero" Tag="both"/><ComboBoxItem Content="Без озвучки" Tag="none"/>
        </ComboBox>
        <WrapPanel x:Name="Voices" Margin="0,8,0,0">
          <CheckBox x:Name="Denis" Content="Денис" Tag="ru_RU-denis-medium" IsChecked="True"/>
          <CheckBox x:Name="Dmitri" Content="Дмитрий" Tag="ru_RU-dmitri-medium"/><CheckBox x:Name="Irina" Content="Ирина" Tag="ru_RU-irina-medium"/><CheckBox x:Name="Ruslan" Content="Руслан" Tag="ru_RU-ruslan-medium"/>
        </WrapPanel>
        <TextBlock x:Name="TtsHint" Text="Скачаются только отмеченные голоса." Foreground="{DynamicResource Muted}" TextWrapping="Wrap" Margin="0,3,0,0"/>
        <CheckBox x:Name="Dodo" Content="Поддержка Додо Ре Ми" Margin="0,20,0,4"/>
        <TextBlock Text="Папка Jackbox Party Pack 10 — необязательно" Margin="0,6,0,6"/>
        <DockPanel><Button x:Name="GameBrowse" Content="Обзор…" DockPanel.Dock="Right" Margin="8,0,0,0" IsEnabled="False"/><TextBox x:Name="GamePath" IsEnabled="False"/></DockPanel>
        <CheckBox x:Name="Cheat" Content="Указать папку с играми для читов" Margin="0,20,0,4"/>
        <TextBlock Text="Папка со всеми Jackbox или отдельной игрой — необязательно" Margin="0,6,0,6"/>
        <DockPanel><Button x:Name="CheatBrowse" Content="Обзор…" DockPanel.Dock="Right" Margin="8,0,0,0" IsEnabled="False"/><TextBox x:Name="CheatPath" IsEnabled="False"/></DockPanel>
        <TextBlock Text="Файлы игр читаются на месте. Без выбранной папки — поиск в Steam." Foreground="{DynamicResource Muted}" TextWrapping="Wrap" Margin="0,5,0,0"/>
        <CheckBox x:Name="Russian" Content="Скачать русский веб-клиент" Margin="0,16,0,4"/>
      </StackPanel>
    </ScrollViewer>
    <Expander x:Name="Details" Grid.Row="2" Header="Журнал" Visibility="Collapsed" Foreground="{DynamicResource Fg}" Margin="0,12,0,0">
      <TextBox x:Name="Log" IsReadOnly="True" Height="120" TextWrapping="Wrap" VerticalScrollBarVisibility="Auto" Margin="0,6,0,0"/>
    </Expander>
    <ProgressBar x:Name="Progress" Grid.Row="3" Height="4" IsIndeterminate="True" Visibility="Collapsed" Foreground="{DynamicResource Accent}" Background="{DynamicResource Field}" Margin="0,10,0,0"/>
    <DockPanel Grid.Row="4" Margin="0,14,0,0">
      <Button x:Name="Download" DockPanel.Dock="Right" Content="Скачать" Width="170" Background="{DynamicResource Accent}" Foreground="{DynamicResource OnAccent}" BorderBrush="{DynamicResource Accent}" Margin="16,0,0,0"/>
      <TextBlock x:Name="Status" Text="Зависимости и выбранные голоса скачаются автоматически." Foreground="{DynamicResource Muted}" TextWrapping="Wrap" VerticalAlignment="Center"/>
    </DockPanel>
  </Grid>
</Window>
'@
$window = [Windows.Markup.XamlReader]::Load((New-Object Xml.XmlNodeReader $xaml))
$ui = @{}
foreach ($name in @('Settings','AppPath','AppBrowse','RuntimePath','RuntimeBrowse','Tts','Voices','TtsHint','Dodo','GamePath','GameBrowse','Cheat','CheatPath','CheatBrowse','Russian','Details','Log','Progress','Download','Status')) { $ui[$name] = $window.FindName($name) }
$script:running = $false
$script:installed = $null
$script:process = $null
$script:themeKey = ''
$script:logText = ''
$work = Join-Path ([IO.Path]::GetTempPath()) ('localbox-download-' + [guid]::NewGuid().ToString('N'))
$ui.AppPath.Text = Join-Path $env:LOCALAPPDATA 'Programs\LocalBox'
$script:defaultRuntime = Join-Path $ui.AppPath.Text 'runtime'
$ui.RuntimePath.Text = $script:defaultRuntime

function Set-Status([string]$Text, [string]$Kind = 'Muted') {
    $ui.Status.Text = $Text
    $ui.Status.SetResourceReference([Windows.Controls.TextBlock]::ForegroundProperty, $Kind)
}

function Update-Theme {
    $light = [Microsoft.Win32.Registry]::GetValue('HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize', 'AppsUseLightTheme', 1)
    $dark = $light -eq 0
    $highContrast = [Windows.SystemParameters]::HighContrast
    $key = "$dark,$highContrast"
    if ($key -eq $script:themeKey) { return }
    $script:themeKey = $key
    $colors = if ($dark) {
        @{Bg='#202124'; Field='#2B2D31'; Fg='#F1F2F3'; Muted='#AEB4BD'; Border='#42474E'; Hover='#373B42'; Accent='#78A9F5'; OnAccent='#122443'; Error='#FFA59E'; Success='#93D9A7'}
    } else {
        @{Bg='#F5F5F5'; Field='#FFFFFF'; Fg='#202124'; Muted='#626872'; Border='#C7CCD3'; Hover='#E6E9EF'; Accent='#2867C8'; OnAccent='#FFFFFF'; Error='#B3261E'; Success='#267139'}
    }
    if ($highContrast) {
        $colors = @{Bg=[Windows.SystemColors]::WindowColor; Field=[Windows.SystemColors]::WindowColor; Fg=[Windows.SystemColors]::WindowTextColor;
                    Muted=[Windows.SystemColors]::WindowTextColor; Border=[Windows.SystemColors]::WindowTextColor; Hover=[Windows.SystemColors]::ControlColor;
                    Accent=[Windows.SystemColors]::HighlightColor; OnAccent=[Windows.SystemColors]::HighlightTextColor;
                    Error=[Windows.SystemColors]::WindowTextColor; Success=[Windows.SystemColors]::WindowTextColor}
    }
    foreach ($name in $colors.Keys) { $window.Resources[$name] = [Windows.Media.BrushConverter]::new().ConvertFromString([string]$colors[$name]) }
    $handle = [Windows.Interop.WindowInteropHelper]::new($window).Handle
    if ($handle -ne [IntPtr]::Zero) {
        $value = [int]$dark
        $result = [LocalBoxWindowTheme]::DwmSetWindowAttribute($handle, 20, [ref]$value, 4)
        if ($result -ne 0) { [void][LocalBoxWindowTheme]::DwmSetWindowAttribute($handle, 19, [ref]$value, 4) }
    }
}

function Load-GamePaths {
    try {
        $file = Join-Path $ui.AppPath.Text 'launcher\localbox-settings.json'
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { return }
        if ($script:loadedTarget -eq $ui.AppPath.Text) { return }
        $saved = Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json
        $ui.GamePath.Text = [string]$saved.jackbox10_path
        $ui.Dodo.IsChecked = [bool]$saved.dodo_render
        $ui.CheatPath.Text = [string]$saved.cheat_content_dir
        $ui.Cheat.IsChecked = [bool]$saved.cheat_content_dir
        $script:loadedTarget = $ui.AppPath.Text
    } catch { }
}

function Update-Options {
    $piper = $ui.Tts.SelectedItem.Tag -in @('piper', 'both')
    $ui.Voices.IsEnabled = $piper
    $ui.TtsHint.Text = if ($piper) { 'Скачаются только отмеченные голоса.' } elseif ($ui.Tts.SelectedItem.Tag -eq 'silero') { 'Скачаются все встроенные русские голоса.' } else { '' }
    $ui.GamePath.IsEnabled = $ui.Dodo.IsChecked -eq $true
    $ui.GameBrowse.IsEnabled = $ui.Dodo.IsChecked -eq $true
    $ui.CheatPath.IsEnabled = $ui.Cheat.IsChecked -eq $true
    $ui.CheatBrowse.IsEnabled = $ui.Cheat.IsChecked -eq $true
}

function Browse-Folder($Field) {
    $dialog = New-Object Windows.Forms.FolderBrowserDialog
    $dialog.SelectedPath = $Field.Text
    $dialog.ShowNewFolderButton = $true
    try { if ($dialog.ShowDialog() -eq [Windows.Forms.DialogResult]::OK) { $Field.Text = $dialog.SelectedPath } }
    finally { $dialog.Dispose() }
}

function Copy-Payload([string]$Destination) {
    $manifestPath = Join-Path $Source 'installer\payload-sha256.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'Не найден список файлов установки. Запустите собранный setup.exe.' }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    foreach ($property in $manifest.PSObject.Properties) {
        $relative = $property.Name.Replace('/', '\')
        $file = Join-Path $Source $relative
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $property.Value) { throw "Не совпала контрольная сумма: $relative" }
    }
    foreach ($property in $manifest.PSObject.Properties) {
        $relative = $property.Name.Replace('/', '\')
        $to = Join-Path $Destination $relative
        New-Item -ItemType Directory -Force -Path (Split-Path $to -Parent) | Out-Null
        Copy-Item -LiteralPath (Join-Path $Source $relative) -Destination $to -Force
    }
}

function Start-Download {
    if ($script:running) { return }
    if ($script:installed) {
        try { Start-Process -FilePath (Join-Path $script:installed 'start-server.bat') -ArgumentList '--gui' -WorkingDirectory $script:installed; $window.Close() }
        catch { Set-Status ('Не удалось открыть LocalBox: ' + $_.Exception.Message) 'Error' }
        return
    }
    try {
        if (-not $ui.AppPath.Text.Trim() -or -not $ui.RuntimePath.Text.Trim()) { throw 'Укажите папки для LocalBox и зависимостей.' }
        $target = [IO.Path]::GetFullPath($ui.AppPath.Text.Trim())
        $runtime = [IO.Path]::GetFullPath($ui.RuntimePath.Text.Trim())
        $voices = @($ui.Voices.Children | Where-Object { $_.IsChecked } | ForEach-Object { $_.Tag })
        $tts = [string]$ui.Tts.SelectedItem.Tag
        if ($tts -in @('piper', 'both') -and $voices.Count -eq 0) { throw 'Выберите хотя бы один голос Piper.' }
        if (Test-Path -LiteralPath $target) {
            if (-not (Test-Path -LiteralPath $target -PathType Container)) { throw 'Путь LocalBox должен быть папкой.' }
            if ((Get-ChildItem -LiteralPath $target -Force | Select-Object -First 1) -and -not (Test-Path -LiteralPath (Join-Path $target 'server\server.js') -PathType Leaf)) {
                throw 'Выберите пустую папку или существующую установку LocalBox.'
            }
        }
        $game = if ($ui.Dodo.IsChecked) { $ui.GamePath.Text.Trim() } else { '' }
        if ($game -and -not (Test-Path -LiteralPath $game -PathType Container)) { throw 'Папка Jackbox 10 не найдена.' }
        $cheat = if ($ui.Cheat.IsChecked) { $ui.CheatPath.Text.Trim() } else { '' }
        if ($ui.Cheat.IsChecked -and -not $cheat) { throw 'Укажите папку с играми для читов или снимите галочку.' }
        if ($cheat -and -not (Test-Path -LiteralPath $cheat -PathType Container)) { throw 'Папка с играми для читов не найдена.' }
        $script:running = $true
        $ui.Settings.IsEnabled = $false
        $ui.Download.IsEnabled = $false
        $ui.Download.Content = 'Скачиваем…'
        $ui.Details.Visibility = 'Visible'
        $ui.Progress.Visibility = 'Visible'
        Set-Status 'Скачиваем и настраиваем LocalBox…'
        $window.Dispatcher.Invoke([Action]{}, [Windows.Threading.DispatcherPriority]::Render)
        Copy-Payload $target
        New-Item -ItemType Directory -Force -Path $work | Out-Null
        $options = Join-Path $work 'options.ini'
        $lines = @('[setup]', "runtime=$runtime", "tts=$tts", ('voices=' + ($voices -join ',')), "game=$game", "cheat_content=$cheat", ('dodo=' + [int][bool]$ui.Dodo.IsChecked), ('russian=' + [int][bool]$ui.Russian.IsChecked))
        [IO.File]::WriteAllLines($options, $lines, [Text.Encoding]::Unicode)
        $script:stdout = Join-Path $work 'stdout.log'
        $script:stderr = Join-Path $work 'stderr.log'
        $script:logText = ''
        $ui.Log.Clear()
        # Windows paths cannot contain a quote; quote every path independently for powershell.exe.
        $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $target 'installer\windows-bootstrap.ps1') + '" -Root "' + $target + '" -OptionsFile "' + $options + '"'
        $script:process = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput $script:stdout -RedirectStandardError $script:stderr
        $script:downloadTarget = $target
    } catch {
        $script:running = $false
        $ui.Settings.IsEnabled = $true
        $ui.Download.IsEnabled = $true
        $ui.Download.Content = 'Скачать'
        $ui.Progress.Visibility = 'Collapsed'
        Set-Status ('Не получилось скачать: ' + $_.Exception.Message) 'Error'
    }
}

function Read-Progress {
    if (-not $script:process) { return }
    $text = ''
    foreach ($file in @($script:stdout, $script:stderr)) {
        if (Test-Path -LiteralPath $file) {
            try {
                $stream = [IO.FileStream]::new($file, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
                $reader = [IO.StreamReader]::new($stream, [Text.Encoding]::UTF8, $true)
                try { $text += $reader.ReadToEnd() + "`r`n" }
                finally { $reader.Dispose() }
            } catch [IO.IOException] { }
        }
    }
    if ($text -ne $script:logText) {
        $script:logText = $text
        $ui.Log.Text = $text
        $ui.Log.ScrollToEnd()
    }
    $script:process.Refresh()
    if (-not $script:process.HasExited) { return }
    $script:process.WaitForExit()
    $code = $script:process.ExitCode
    $script:process.Dispose()
    $script:process = $null
    $script:running = $false
    $ui.Progress.Visibility = 'Collapsed'
    $ui.Download.IsEnabled = $true
    if ($code -eq 0) {
        $script:installed = $script:downloadTarget
        Set-Status 'Готово. Можно открыть LocalBox.' 'Success'
        $ui.Download.Content = 'Открыть LocalBox'
        try {
            $shell = New-Object -ComObject WScript.Shell
            $menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'LocalBox'
            New-Item -ItemType Directory -Force -Path $menu | Out-Null
            foreach ($shortcutPath in @((Join-Path $menu 'LocalBox.lnk'), (Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'LocalBox.lnk'))) {
                $shortcut = $shell.CreateShortcut($shortcutPath)
                $shortcut.TargetPath = Join-Path $script:installed 'start-server.bat'
                $shortcut.WorkingDirectory = $script:installed
                $shortcut.Save()
            }
        } catch { $ui.Log.AppendText("`r`nНе удалось добавить ярлык: " + $_.Exception.Message) }
    } else {
        $ui.Settings.IsEnabled = $true
        $ui.Download.Content = 'Скачать'
        Set-Status 'Не получилось скачать. Подробности — в журнале.' 'Error'
        $ui.Details.IsExpanded = $true
    }
}

$ui.AppPath.Add_TextChanged({
    try {
        $next = Join-Path $ui.AppPath.Text 'runtime'
        if ($ui.RuntimePath.Text -eq $script:defaultRuntime) { $ui.RuntimePath.Text = $next }
        $script:defaultRuntime = $next
        Load-GamePaths
    } catch { }
})
$ui.AppBrowse.Add_Click({ Browse-Folder $ui.AppPath })
$ui.RuntimeBrowse.Add_Click({ Browse-Folder $ui.RuntimePath })
$ui.GameBrowse.Add_Click({ Browse-Folder $ui.GamePath })
$ui.CheatBrowse.Add_Click({ Browse-Folder $ui.CheatPath })
$ui.Cheat.Add_Checked({ Update-Options })
$ui.Cheat.Add_Unchecked({ Update-Options })
$ui.Tts.Add_SelectionChanged({ Update-Options })
$ui.Dodo.Add_Checked({ Update-Options })
$ui.Dodo.Add_Unchecked({ Update-Options })
$ui.Download.Add_Click({ Start-Download })
$window.Add_Closing({
    param($sender, $eventArgs)
    if ($script:running) { $eventArgs.Cancel = $true; Set-Status 'Скачивание ещё идёт. Дождитесь окончания.' }
})
$themeTimer = New-Object Windows.Threading.DispatcherTimer
$themeTimer.Interval = [TimeSpan]::FromSeconds(2)
$themeTimer.Add_Tick({ Update-Theme })
$progressTimer = New-Object Windows.Threading.DispatcherTimer
$progressTimer.Interval = [TimeSpan]::FromMilliseconds(300)
$progressTimer.Add_Tick({
    try { Read-Progress }
    catch { $ui.Log.AppendText("`r`n" + $_.Exception.Message); $ui.Details.IsExpanded = $true }
})
$window.Add_SourceInitialized({ $script:themeKey = ''; Update-Theme })
Load-GamePaths
Update-Options
Update-Theme
$themeTimer.Start()
$progressTimer.Start()
try { [void]$window.ShowDialog() }
finally {
    $themeTimer.Stop()
    $progressTimer.Stop()
    if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force }
}
