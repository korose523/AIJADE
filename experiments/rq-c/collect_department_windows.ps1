[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Since,
    [Parameter(Mandatory=$true)][string]$Until,
    [Parameter(Mandatory=$true)][string]$ExpectedHelperSha256,
    [Parameter(Mandatory=$true)][string]$NvidiaSmi,
    [Parameter(Mandatory=$true)][string]$NvidiaSmiSha256,
    [Parameter(Mandatory=$true)][string]$GpuUuid
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$WarningPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$script:Utf8 = [Text.UTF8Encoding]::new($false)
$script:RemainingXmlBytes = 8 * 1024 * 1024
[Console]::OutputEncoding = $script:Utf8
$culture = [Globalization.CultureInfo]::InvariantCulture

function Format-Utc([datetime]$Time) {
    return $Time.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffffff'Z'", $culture)
}

function Confirm-Pin([string]$Path, [string]$Expected) {
    if ($Expected -cnotmatch '^[0-9a-f]{64}$' -or
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Expected) {
        throw 'A reviewed Windows tool or helper differs from its SHA-256.'
    }
}

function Read-Identity {
    $os = Get-CimInstance -ClassName Win32_OperatingSystem -Property CSName, LastBootUpTime, Version, BuildNumber
    $machineGuid = (Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Cryptography' -Name MachineGuid).MachineGuid
    $gpu = @(& $NvidiaSmi -i $GpuUuid '--query-gpu=uuid,driver_version' '--format=csv,noheader,nounits')
    if ($LASTEXITCODE -ne 0 -or $gpu.Count -ne 1) {
        throw 'The native NVIDIA runtime did not return one assigned GPU and driver version.'
    }
    $match = [regex]::Match($gpu[0], '^(GPU-[0-9a-f-]{36}),\s*([0-9]+(?:\.[0-9]+){1,3})$', 'IgnoreCase')
    if (-not $match.Success -or $match.Groups[1].Value -ine $GpuUuid) {
        throw 'The native NVIDIA runtime did not return one assigned GPU and driver version.'
    }
    return [ordered]@{
        machineGuid = [string]$machineGuid
        computer = [string]$os.CSName
        bootAt = Format-Utc $os.LastBootUpTime
        osVersion = [string]$os.Version
        osBuild = [string]$os.BuildNumber
        gpu = $match.Groups[1].Value
        driver = $match.Groups[2].Value
    }
}

function Open-EventReader([string]$Channel, [string]$Query) {
    $request = [Diagnostics.Eventing.Reader.EventLogQuery]::new($Channel, 'LogName', $Query)
    $request.TolerateQueryErrors = $false
    return [Diagnostics.Eventing.Reader.EventLogReader]::new($request)
}

function Read-RawXml($Record) {
    $raw = $Record.ToXml()
    $script:RemainingXmlBytes -= $script:Utf8.GetByteCount($raw)
    if ($script:RemainingXmlBytes -lt 0) {
        throw 'The Windows Event Log capture exceeds its raw XML budget.'
    }
    return $raw
}

function Read-Anchor([string]$Channel) {
    $log = Get-WinEvent -ListLog $Channel
    if (-not $log.IsEnabled -or $null -eq $log.RecordCount -or $log.RecordCount -le 0 -or
        $null -eq $log.OldestRecordNumber -or [string]::IsNullOrEmpty($log.LogFilePath)) {
        throw "The $Channel Event Log has no enabled, retained coverage witness."
    }
    $reader = Open-EventReader $Channel '*'
    try {
        $record = $reader.ReadEvent()
        if ($null -eq $record) { throw "The $Channel Event Log returned no coverage witness." }
        try {
            if ($record.RecordId -ne $log.OldestRecordNumber) {
                throw "The $Channel Event Log retention boundary changed while it was read."
            }
            return [ordered]@{
                oldestRecordId = [long]$log.OldestRecordNumber
                recordCount = [long]$log.RecordCount
                logFilePath = [string]$log.LogFilePath
                logMode = [string]$log.LogMode
                xml = Read-RawXml $record
            }
        } finally { $record.Dispose() }
    } finally { $reader.Dispose() }
}

function Read-Window([string]$Channel, [string]$XPath) {
    $reader = Open-EventReader $Channel $XPath
    $count = 0
    try {
        while ($null -ne ($record = $reader.ReadEvent())) {
            try {
                $count++
                if ($count -gt 12000) { throw "The $Channel Event Log interval exceeds its record budget." }
                Read-RawXml $record
            } finally { $record.Dispose() }
        }
    } finally { $reader.Dispose() }
}

Confirm-Pin $PSCommandPath $ExpectedHelperSha256
if ($NvidiaSmi -notmatch '^[A-Za-z]:\\(?:[^"\r\n]+\\)?nvidia-smi\.exe$' -or
    $GpuUuid -notmatch '^GPU-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$') {
    throw 'An absolute native NVIDIA-SMI path and an assigned GPU UUID are required.'
}
$nvidiaDrive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($NvidiaSmi))
if ($nvidiaDrive.DriveType -eq [IO.DriveType]::Network) { throw 'NVIDIA-SMI must be local to the Windows host.' }
Confirm-Pin $NvidiaSmi $NvidiaSmiSha256
$started = [datetime]::UtcNow
$start = [datetimeoffset]::Parse($Since, $culture).UtcDateTime
$end = [datetimeoffset]::Parse($Until, $culture).UtcDateTime
if ($start -ge $end -or $end -gt $started) { throw 'Invalid or future Windows Event Log cutoff.' }
$bootBefore = Read-Identity
$startText = Format-Utc $start
$endText = Format-Utc $end
$xpath = "*[System[TimeCreated[@SystemTime >= '$startText' and @SystemTime < '$endText']]]"
$channels = [ordered]@{}
foreach ($channel in @('System', 'Application')) {
    $anchor = Read-Anchor $channel
    $events = @(Read-Window $channel $xpath)
    $channels[$channel] = [ordered]@{
        xpath = $xpath
        before = $anchor
        events = $events
        after = Read-Anchor $channel
    }
}
$bootAfter = Read-Identity
Confirm-Pin $NvidiaSmi $NvidiaSmiSha256
Confirm-Pin $PSCommandPath $ExpectedHelperSha256
$report = ConvertTo-Json -Depth 8 -Compress -InputObject ([ordered]@{
    schema = 'aijade.p2-r.windows-event-native-export.v1'
    powershellVersion = $PSVersionTable.PSVersion.ToString()
    startedAt = Format-Utc $started
    finishedAt = Format-Utc ([datetime]::UtcNow)
    identityBefore = $bootBefore
    identityAfter = $bootAfter
    channels = $channels
})
if ($script:Utf8.GetByteCount($report) -gt 32 * 1024 * 1024) {
    throw 'The Windows Event Log export exceeds its JSON byte budget.'
}
[Console]::Out.WriteLine($report)
