<#
.SYNOPSIS
    Find the Last War client process(es) and list their live TCP connections.

.DESCRIPTION
    Runs on the WINDOWS side (where the game runs), not in WSL.
    Locates processes whose name matches the game/emulator, then prints every
    established/listening TCP endpoint they own: RemoteAddress, RemotePort,
    State, and (best-effort) the resolved hostname.

    Use the RemotePort values to scope the Wireshark capture and to point the
    Lua dissector (tools/lastwar_dissector.lua) at the right port(s).

.PARAMETER NameFilter
    Regex matched against process names. Default covers the official FUNFLY
    client plus the common Android emulators used to run the game.

.PARAMETER IncludeUdp
    Also list UDP endpoints (useful to spot QUIC on UDP/443).

.PARAMETER Watch
    Re-scan every 2s until Ctrl+C. Handy to catch short-lived login/gateway
    connections that only exist during startup.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\tools\find_lastwar_connections.ps1

.EXAMPLE
    .\tools\find_lastwar_connections.ps1 -Watch -IncludeUdp
#>
[CmdletBinding()]
param(
    [string] $NameFilter = 'lastwar|LastWar|FUNFLY|funfly|HD-Player|BlueStacks|LdVBoxHeadless|dnplayer|MEmu|NoxVMHandle',
    [switch] $IncludeUdp,
    [switch] $Watch
)

function Resolve-HostSafe([string] $ip) {
    if ([string]::IsNullOrEmpty($ip) -or $ip -eq '0.0.0.0' -or $ip -eq '::' -or $ip -eq '127.0.0.1') { return '' }
    try { return ([System.Net.Dns]::GetHostEntry($ip)).HostName } catch { return '' }
}

function Scan {
    $procs = Get-Process | Where-Object { $_.ProcessName -match $NameFilter }
    if (-not $procs) {
        Write-Host "No matching process found (filter: $NameFilter)." -ForegroundColor Yellow
        Write-Host "Is the game running? Adjust -NameFilter if the exe name differs." -ForegroundColor Yellow
        return
    }

    foreach ($p in $procs) {
        Write-Host ("`n=== {0}  (PID {1}) ===" -f $p.ProcessName, $p.Id) -ForegroundColor Cyan

        $tcp = Get-NetTCPConnection -OwningProcess $p.Id -ErrorAction SilentlyContinue |
               Sort-Object State, RemotePort
        if ($tcp) {
            $tcp | ForEach-Object {
                [pscustomobject]@{
                    Proto         = 'TCP'
                    LocalPort     = $_.LocalPort
                    RemoteAddress = $_.RemoteAddress
                    RemotePort    = $_.RemotePort
                    State         = $_.State
                    Host          = Resolve-HostSafe $_.RemoteAddress
                }
            } | Format-Table -AutoSize
        } else {
            Write-Host '  (no TCP connections)' -ForegroundColor DarkGray
        }

        if ($IncludeUdp) {
            $udp = Get-NetUDPEndpoint -OwningProcess $p.Id -ErrorAction SilentlyContinue
            if ($udp) {
                Write-Host '  UDP endpoints (watch for QUIC on :443):' -ForegroundColor DarkGray
                $udp | Select-Object LocalAddress, LocalPort | Format-Table -AutoSize
            }
        }
    }

    # A compact list of distinct remote ports — copy these into the dissector / capture filter.
    $ports = $procs | ForEach-Object {
        Get-NetTCPConnection -OwningProcess $_.Id -State Established -ErrorAction SilentlyContinue
    } | Select-Object -ExpandProperty RemotePort -Unique | Sort-Object
    if ($ports) {
        Write-Host ("`nDistinct established remote ports: {0}" -f ($ports -join ', ')) -ForegroundColor Green
        Write-Host ("Wireshark filter: tcp.port == {0}" -f ($ports -join ' || tcp.port == ')) -ForegroundColor Green
    }
}

if ($Watch) {
    Write-Host 'Watching (Ctrl+C to stop)...' -ForegroundColor Magenta
    while ($true) { Clear-Host; Scan; Start-Sleep -Seconds 2 }
} else {
    Scan
}
