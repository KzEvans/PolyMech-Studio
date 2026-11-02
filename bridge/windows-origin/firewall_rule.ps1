# Allow inbound TCP to the bridge port ONLY from the Mac's address on the Parallels shared network.
# Params: $MacIp (e.g. the Mac's bridge100 address), $Port (default 8766). Requires admin (SYSTEM via prlctl).
# Undo:  Remove-NetFirewallRule -DisplayName "PolyMech Origin Bridge"
$ErrorActionPreference = "Stop"
if (-not $Port) { $Port = "8766" }
if (-not ($MacIp -match '^\d{1,3}(\.\d{1,3}){3}$')) { throw "MacIp must be an IPv4 address" }
$name = "PolyMech Origin Bridge"
Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port `
    -RemoteAddress $MacIp -Profile Any -Description "PolyMech Studio: Mac -> Origin Bridge only" | Out-Null
Get-NetFirewallRule -DisplayName $name | Get-NetFirewallAddressFilter | Select-Object RemoteAddress | Format-List | Out-String
