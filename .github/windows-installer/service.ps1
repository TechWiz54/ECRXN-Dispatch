<#
    Runs ECRXN Dispatch in the background on Windows. Used by the setup program and the tray icon's menu;
    you don't need to run it yourself.

      service.ps1 -Install [-Port 9911] [-Firewall]   start at boot (scheduled task, as SYSTEM) and start now
      service.ps1 -Start | -Stop | -Restart           (-Restart -Port N also moves the firewall rule to port N)
      service.ps1 -Uninstall                          remove the task and the firewall rule
#>
param(
    [switch]$Install,
    [switch]$Start,
    [switch]$Restart,
    [switch]$Stop,
    [switch]$Uninstall,
    [int]$Port = 0,
    [switch]$Firewall,
    [switch]$All      # with -Stop: the tray icon too (the setup does this before replacing files)
)
$ErrorActionPreference = 'Stop'
$Task = 'ECRXN Dispatch'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)   # the install folder
$Py = Join-Path $Root 'python\pythonw.exe'

# The task runs as SYSTEM, so starting / stopping it needs admin rights: ask for them (tray icon menu)
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    $mode = if ($Restart) { '-Restart' } elseif ($Stop) { '-Stop' } elseif ($Start) { '-Start' } else { $null }
    if ($mode) {
        if ($Port -gt 0) { $mode += " -Port $Port" }
        Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`" $mode"
        exit
    }
    throw "Run this as an administrator."
}

# Python processes started from this folder. -WithTray also stops the tray icon (for updates / uninstall).
function Stop-App([switch]$WithTray) {
    Stop-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Root, [StringComparison]::OrdinalIgnoreCase) } |
        Where-Object { $WithTray -or $_.CommandLine -notmatch 'tray\.py' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Remove-Old {
    # the earlier script-based install used these names
    foreach ($name in 'iCAD Dispatch', $Task) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
        Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    }
}

if ($Install) {
    Stop-App -WithTray
    Remove-Old
    $action = New-ScheduledTaskAction -Execute $Py -Argument "`"$Root\serve.py`"" -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $Task -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
    if ($Firewall -and $Port -gt 0) {
        New-NetFirewallRule -DisplayName $Task -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
    }
    Start-ScheduledTask -TaskName $Task
}
elseif ($Start) {
    Start-ScheduledTask -TaskName $Task
}
elseif ($Restart) {
    Stop-App
    if ($Port -gt 0) {
        # the port changed in Settings: move the firewall rule with it (if there is one)
        Get-NetFirewallRule -DisplayName $Task -ErrorAction SilentlyContinue | Set-NetFirewallRule -LocalPort $Port
    }
    Start-Sleep -Seconds 1
    Start-ScheduledTask -TaskName $Task
}
elseif ($Stop) {
    Stop-App -WithTray:$All
}
elseif ($Uninstall) {
    Stop-App -WithTray
    Remove-Old
}
