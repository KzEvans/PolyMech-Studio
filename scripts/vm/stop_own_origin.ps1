# Stop Origin automation instances created by this project, identified by explicit PID list
# ($Pids, comma-separated) AND command line "-Embedding". Never touches other Origin processes.
foreach ($id in ($Pids -split ",")) {
  $p = Get-CimInstance Win32_Process -Filter "ProcessId=$id"
  if ($p -and $p.Name -eq "Origin64.exe" -and $p.CommandLine -like "*-Embedding*") {
    Stop-Process -Id $id -Force; "stopped $id (created $($p.CreationDate))"
  } else { "skipped $id" }
}
