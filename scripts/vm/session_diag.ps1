# Compare this process's logon context with explorer.exe's (read-only diagnostic).
"--- this process"
whoami /groups | Select-String -Pattern "Mandatory Label|High|Medium" | ForEach-Object { $_.Line.Substring(0, [Math]::Min(60, $_.Line.Length)) }
"elevated=" + ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
"logon id=" + ((whoami /logonid) -join "")
"C:\Mac\Home\Desktop\Origin exists: " + (Test-Path "C:\Mac\Home\Desktop\Origin\Origin.ini")
"\\psf\Home exists: " + (Test-Path "\\psf\Home")
"--- explorer.exe owner logon session"
$ex = Get-CimInstance Win32_Process -Filter "Name='explorer.exe'" | Select-Object -First 1
$ls = Get-CimAssociatedInstance -InputObject $ex -ResultClassName Win32_LogonSession -ErrorAction SilentlyContinue
"explorer pid=" + $ex.ProcessId
Get-CimInstance Win32_LogonSession | Where-Object { $_.LogonType -in 2,10,11 } | ForEach-Object {
  $u = Get-CimAssociatedInstance -InputObject $_ -ResultClassName Win32_Account -ErrorAction SilentlyContinue | Select-Object -First 1
  "logon session " + $_.LogonId + " type=" + $_.LogonType + " start=" + $_.StartTime + " user=" + $u.Name
}
