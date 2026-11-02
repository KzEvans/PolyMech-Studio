# Stop and remove the bridge autostart task (the bridge exits; owned Origin instances are closed by it).
$name = "PolyMech Origin Bridge"
if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    "removed"
} else { "not installed" }
