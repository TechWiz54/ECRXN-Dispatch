<#
    Runs ECRXN Dispatch in the background on Windows. Called by the setup program (and the Start menu's
    "Restart ECRXN Dispatch"); you don't need to run it yourself.

      service.ps1 -Install [-Port 9911] [-Firewall]   start at boot (scheduled task, as SYSTEM) and start now
      service.ps1 -Restart                            stop and start again (after editing .env)
      service.ps1 -Stop
      service.ps1 -Uninstall                          remove the task and the firewall rule
#>
param(
    [switch]$Install,
    [switch]$Restart,
    [switch]$Stop,
    [switch]$Uninstall,
    [int]$Port = 9911,
    [switch]$Firewall
)
$ErrorActionPreference = 'Stop'
$Task = 'ECRXN Dispatch'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)   # the install folder
$Py = Join-Path $Root 'python\pythonw.exe'

# The task runs as SYSTEM, so stopping / starting it needs admin rights: ask for them (Start menu shortcut)
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    $mode = if ($Restart) { '-Restart' } elseif ($Stop) { '-Stop' } else { $null }
    if ($mode) {
        Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`" $mode"
        exit
    }
    throw "Run this as an administrator."
}

function Stop-App {
    Stop-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
    # a pythonw.exe from this folder that is still running (e.g. started by hand)
    Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Root, [StringComparison]::OrdinalIgnoreCase) } |
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
    Stop-App
    Remove-Old
    $action = New-ScheduledTaskAction -Execute $Py -Argument "`"$Root\serve.py`"" -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $Task -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
    if ($Firewall) {
        New-NetFirewallRule -DisplayName $Task -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
    }
    Start-ScheduledTask -TaskName $Task
}
elseif ($Restart) {
    Stop-App
    Start-Sleep -Seconds 1
    Start-ScheduledTask -TaskName $Task
}
elseif ($Stop) {
    Stop-App
}
elseif ($Uninstall) {
    Stop-App
    Remove-Old
}
