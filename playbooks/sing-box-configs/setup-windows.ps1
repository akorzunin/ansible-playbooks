# Published with the private Windows profile URL substituted by generate.py.
# Run in an Administrator PowerShell window (Windows 10/11, x64 or ARM64).
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProfileUrl = '__PROFILE_URL__'
$Root = Join-Path $env:ProgramData 'sing-box-remote'
$TaskName = 'sing-box-remote-profile'
$Config = Join-Path $Root 'config.json'
$Work = $null
$Lock = $null
$Client = $null
$Stage = 'Open PowerShell as Administrator, then run the setup link again.'

try {
    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
    if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Open PowerShell as Administrator, then run the setup link again.'
    }
    $Stage = 'Check directory permissions and whether another update is running.'
    Add-Type -AssemblyName System.Net.Http
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    # Only Administrators and SYSTEM may read credentials or change the task's executable.
    & icacls.exe $Root /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot protect the configuration directory.' }
    # One installed profile; an exclusive file handle serializes manual updates.
    $Lock = [IO.File]::Open((Join-Path $Root '.update-lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $Work = Join-Path $Root ([IO.Path]::GetRandomFileName())
    New-Item -ItemType Directory -Path $Work | Out-Null
    $Handler = New-Object Net.Http.HttpClientHandler
    $Handler.UseProxy = $false
    $Handler.AllowAutoRedirect = $false
    $Client = New-Object Net.Http.HttpClient($Handler)
    $Client.Timeout = [TimeSpan]::FromSeconds(300)

    function Receive-File([string]$Url, [string]$Destination, [bool]$ReleaseAsset = $false) {
        # Profile URLs never redirect. Only release assets may follow HTTPS CDN redirects.
        for ($Redirect = 0; $Redirect -lt 6; $Redirect++) {
            $Uri = [Uri]$Url
            if ($Uri.Scheme -ne 'https' -or $Uri.UserInfo) { throw 'HTTPS is required.' }
            $Response = $Client.GetAsync($Uri).GetAwaiter().GetResult()
            try {
                if ($ReleaseAsset -and [int]$Response.StatusCode -in 301, 302, 303, 307, 308) {
                    $Url = ([Uri]::new($Uri, $Response.Headers.Location)).AbsoluteUri
                    continue
                }
                if ([int]$Response.StatusCode -ne 200) { throw 'Download failed.' }
                $Bytes = $Response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
                if (-not $ReleaseAsset -and $Bytes.Length -gt 1048576) { throw 'Profile is too large.' }
                [IO.File]::WriteAllBytes($Destination, $Bytes)
                return
            } finally { $Response.Dispose() }
        }
        throw 'Too many download redirects.'
    }

    $Stage = 'Check direct HTTPS access to GitHub and supported x64/ARM64 architecture.'
    $CoreDir = Join-Path $Root 'core'
    $Core = Join-Path $CoreDir 'sing-box.exe'
    if (-not (Test-Path $Core)) {
        $Installed = Get-Command sing-box.exe -CommandType Application -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force -Path $CoreDir | Out-Null
        if ($Installed) {
            # Copy into the protected directory before running as SYSTEM.
            Copy-Item $Installed.Source $Core
            $Cronet = Join-Path (Split-Path $Installed.Source) 'libcronet.dll'
            if (Test-Path $Cronet) { Copy-Item $Cronet $CoreDir }
        } else {
            $Arch = [Environment]::GetEnvironmentVariable('PROCESSOR_ARCHITEW6432')
            if (-not $Arch) { $Arch = $env:PROCESSOR_ARCHITECTURE }
            switch ($Arch) {
                'AMD64' { $Arch = 'amd64'; $Hash = 'c2d8bfff918755808781dfdeeb8581b6c91eb3a243d9a7b55483cfc0c0684d32' }
                'ARM64' { $Arch = 'arm64'; $Hash = '2bb467039310452380958b821983d5bb4f78fb70a2583914e4bea8b011582b64' }
                default { throw 'Unsupported Windows architecture; use x64 or ARM64.' }
            }
            Write-Host 'Installing sing-box 1.14.2...'
            $Archive = "sing-box-1.14.2-windows-$Arch"
            $Zip = Join-Path $Work 'core.zip'
            Receive-File "https://github.com/SagerNet/sing-box/releases/download/v1.14.2/$Archive.zip" $Zip $true
            if ((Get-FileHash $Zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Hash) {
                throw 'Core checksum mismatch.'
            }
            Expand-Archive $Zip (Join-Path $Work 'unpacked')
            # Keep the bundled libcronet.dll beside the executable for Naive support.
            Copy-Item (Join-Path $Work "unpacked/$Archive/*") $CoreDir -Recurse -Force
        }
    }

    $Stage = 'Check profile hosting and use a Naive-enabled sing-box 1.14+ core (with libcronet.dll).'
    $Candidate = Join-Path $Work 'config.json'
    Receive-File $ProfileUrl $Candidate
    & $Core check -c $Candidate *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'Validation failed. Use a Naive-enabled sing-box 1.14+ core; the existing config was not changed.'
    }
    $Stage = 'Quit any existing sing-box GUI/service before enrolling; check Task Scheduler for startup failures.'
    $OldTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $OldTask -and (Get-Process sing-box -ErrorAction SilentlyContinue)) {
        throw 'Quit the existing sing-box client/service before enrolling this managed instance.'
    }
    $Previous = Join-Path $Work 'previous.json'
    $HadConfig = Test-Path $Config
    if ($HadConfig) { Copy-Item $Config $Previous }
    # Use a scheduled task: the CLI executable is not a Windows service binary.
    $Action = New-ScheduledTaskAction -Execute $Core -Argument "run -c `"$Config`"" -WorkingDirectory $Root
    $Trigger = New-ScheduledTaskTrigger -AtStartup
    $TaskPrincipal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    try {
        if ($OldTask) {
            Stop-ScheduledTask -TaskName $TaskName
            for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
                if ((Get-ScheduledTask -TaskName $TaskName).State -ne 'Running') { break }
                Start-Sleep -Milliseconds 250
            }
            if ((Get-ScheduledTask -TaskName $TaskName).State -eq 'Running') { throw 'Existing task did not stop.' }
        }
        if ($HadConfig) {
            [IO.File]::Replace($Candidate, $Config, $null)
        } else {
            [IO.File]::Move($Candidate, $Config)
        }
        Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $TaskPrincipal -Settings $Settings -Force | Out-Null
        Start-ScheduledTask -TaskName $TaskName
        Start-Sleep -Seconds 3
        # Immediate process liveness only; this is not a connectivity test.
        if ((Get-ScheduledTask -TaskName $TaskName).State -ne 'Running') { throw 'Core startup failed.' }
    } catch {
        $NewTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($NewTask) { Stop-ScheduledTask -TaskName $TaskName }
        if ($HadConfig) { Copy-Item $Previous $Config -Force } else { Remove-Item $Config -Force -ErrorAction SilentlyContinue }
        if ($OldTask) {
            Register-ScheduledTask -TaskName $TaskName -InputObject $OldTask -Force | Out-Null
            Start-ScheduledTask -TaskName $TaskName
        } elseif ($NewTask) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        }
        throw 'Startup failed; previous configuration restored. Check Task Scheduler.'
    }
    Write-Host 'Profile refreshed; sing-box is running (starts again at boot).'
    Write-Host 'Dashboard: https://yacd.metacubex.one | API: http://127.0.0.1:9091 | secret: admin'
} catch {
    # HTTP/core exceptions may contain enrollment URLs or credentials; do not print them.
    Write-Host "Setup failed. $Stage" -ForegroundColor Red
    Write-Host 'Existing config is retained/restored unless rollback itself failed; inspect the managed directory if needed.'
    throw 'sing-box setup failed (details suppressed to protect credentials).'
} finally {
    if ($Client) { $Client.Dispose() }
    if ($Work -and (Test-Path $Work)) { Remove-Item $Work -Recurse -Force }
    if ($Lock) { $Lock.Dispose() }
}
