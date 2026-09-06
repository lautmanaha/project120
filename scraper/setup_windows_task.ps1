# פרויקט 120 - רישום משימה יומית ב-Windows Task Scheduler
# הרצה (PowerShell כמנהל, מתוך תיקיית הפרויקט):  .\scraper\setup_windows_task.ps1
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = (Get-Command python).Source
$action = New-ScheduledTaskAction -Execute $python -Argument "scraper\daily_update.py" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At 09:30
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName "Project120 - CEC polls daily" -Action $action -Trigger $trigger -Settings $settings -Description "משיכת סקרים חדשים מאתר ועדת הבחירות ועדכון מסד הנתונים" -Force
Write-Host "נרשמה משימה יומית 09:30. לבדיקה: Get-ScheduledTask 'Project120 - CEC polls daily'"
