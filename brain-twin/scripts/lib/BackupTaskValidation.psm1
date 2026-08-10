# Brain Twin - Validation logic for the Windows backup task.
#
# NOTE: ASCII-only by design (see scripts/setup.ps1 for why).
#
# Pure validation functions only, kept separate from side-effecting calls
# such as Register-ScheduledTask. Imported by install_backup_task.ps1 via
# Import-Module, and tested directly by
# scripts/tests/BackupTaskValidation.Tests.ps1 (Pester).

function Test-HourMinuteRange {
    <#
    .SYNOPSIS
        Validates that Hour (0-23) and Minute (0-59) are within range.
    .OUTPUTS
        [pscustomobject] @{ IsValid = [bool]; Message = [string] }
    #>
    param(
        [Parameter(Mandatory)][int]$Hour,
        [Parameter(Mandatory)][int]$Minute
    )

    if ($Hour -lt 0 -or $Hour -gt 23) {
        return [pscustomobject]@{ IsValid = $false; Message = "Hour must be an integer from 0 to 23 (got: $Hour)" }
    }
    if ($Minute -lt 0 -or $Minute -gt 59) {
        return [pscustomobject]@{ IsValid = $false; Message = "Minute must be an integer from 0 to 59 (got: $Minute)" }
    }
    return [pscustomobject]@{ IsValid = $true; Message = "OK" }
}

function Test-DockerAvailable {
    <#
    .SYNOPSIS
        Checks whether Docker (Docker Desktop) appears to be running. The
        command that is actually invoked can be injected, so this is
        mockable in tests.
    #>
    param(
        [scriptblock]$InvokeDockerInfo = { docker info *> $null; return $LASTEXITCODE }
    )
    try {
        $code = & $InvokeDockerInfo
        return ($code -eq 0)
    } catch {
        return $false
    }
}

function Get-BackupTaskActionArguments {
    <#
    .SYNOPSIS
        Builds the powershell.exe argument string passed to the Task
        Scheduler. The path is quoted (not concatenated as a raw string) so
        that spaces or non-ASCII characters in the path do not break it.
    #>
    param(
        [Parameter(Mandatory)][string]$BackupScriptPath
    )
    return "-NoProfile -ExecutionPolicy Bypass -File `"$BackupScriptPath`""
}

Export-ModuleMember -Function Test-HourMinuteRange, Test-DockerAvailable, Get-BackupTaskActionArguments
