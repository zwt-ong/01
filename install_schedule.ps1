param([switch]$Remove, [switch]$Repair)
$ErrorActionPreference = 'Stop'
$taskName = 'OpportunityRadar-Daily'
if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output 'OpportunityRadar-Daily removed.'
    exit
}
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask -and -not $Repair) {
    Write-Output 'An OpportunityRadar-Daily task already exists. No changes made.'
    exit
}
$taskPythonExe = (Get-Command python -ErrorAction Stop).Source
$taskPythonWindowless = Join-Path (Split-Path $taskPythonExe -Parent) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $taskPythonWindowless)) {
    throw 'pythonw.exe is unavailable. Keep the app running for its built-in scheduler, or install Python with pythonw.exe.'
}
$projectRoot = $PSScriptRoot
$scriptPath = Join-Path $projectRoot 'app.py'
if ($existingTask -and $existingTask.Actions.WorkingDirectory -ne $projectRoot) {
    throw 'Existing task belongs to another location; refusing to replace it.'
}
$beijingZone = [TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$beijingNow = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $beijingZone)
$nextMidnight = [DateTime]::SpecifyKind($beijingNow.Date.AddDays(1), [DateTimeKind]::Unspecified)
$midnightUtc = [TimeZoneInfo]::ConvertTimeToUtc($nextMidnight, $beijingZone)
$localMidnight = [TimeZoneInfo]::ConvertTimeFromUtc($midnightUtc, [TimeZoneInfo]::Local)
if ([TimeZoneInfo]::Local.SupportsDaylightSavingTime) {
    throw 'This local timezone uses DST. Keep the app running for its Beijing-time scheduler instead of installing a local-time Windows task.'
}
$action = New-ScheduledTaskAction -Execute $taskPythonWindowless -Argument ('"' + $scriptPath + '" collect --scheduled') -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $localMidnight
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15)
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Opportunity Radar: collect the previous Beijing day at 00:00. Runs only when this user is logged in; catch up after a missed start.' -Force:$Repair | Select-Object TaskName, State
Write-Output 'Installed for Beijing 00:00. Requires a logged-in session; sleeping/offline PCs catch up when available.'
