# Brain Twin - Pester tests for scripts/lib/BackupTaskValidation.psm1.
#
# NOTE: ASCII-only by design (see scripts/setup.ps1 for why). Where a test
# needs to exercise non-ASCII characters (e.g. a Japanese path segment), the
# string is built from character codes at runtime instead of being written
# as a literal non-ASCII string in this file, so the file itself stays
# pure ASCII.
#
# How to run (Windows PowerShell, Pester 5.x):
#   Install-Module -Name Pester -Force -SkipPublisherCheck   # if not installed
#   Invoke-Pester .\scripts\tests\BackupTaskValidation.Tests.ps1 -Output Detailed
#
# IMPORTANT: this repository's development sandbox has no Windows/PowerShell,
# so this test file has been implemented but not executed there (it must be
# run in your own Windows environment). See VERIFICATION.md.

BeforeAll {
    Import-Module (Join-Path $PSScriptRoot "..\lib\BackupTaskValidation.psm1") -Force
}

Describe "Test-HourMinuteRange" {
    It "0:00 is valid" {
        (Test-HourMinuteRange -Hour 0 -Minute 0).IsValid | Should -BeTrue
    }
    It "23:59 is valid (upper boundary)" {
        (Test-HourMinuteRange -Hour 23 -Minute 59).IsValid | Should -BeTrue
    }
    It "hour 24 is invalid" {
        (Test-HourMinuteRange -Hour 24 -Minute 0).IsValid | Should -BeFalse
    }
    It "hour -1 is invalid" {
        (Test-HourMinuteRange -Hour -1 -Minute 0).IsValid | Should -BeFalse
    }
    It "minute 60 is invalid" {
        (Test-HourMinuteRange -Hour 3 -Minute 60).IsValid | Should -BeFalse
    }
    It "minute -1 is invalid" {
        (Test-HourMinuteRange -Hour 3 -Minute -1).IsValid | Should -BeFalse
    }
    It "returns a message explaining why, when invalid" {
        $result = Test-HourMinuteRange -Hour 99 -Minute 0
        $result.Message | Should -Match "Hour"
    }
}

Describe "Test-DockerAvailable" {
    It "returns true when docker info succeeds (exit code 0)" {
        $result = Test-DockerAvailable -InvokeDockerInfo { return 0 }
        $result | Should -BeTrue
    }
    It "returns false when docker info fails (non-zero exit code)" {
        $result = Test-DockerAvailable -InvokeDockerInfo { return 1 }
        $result | Should -BeFalse
    }
    It "returns false (without crashing) if docker itself is missing and throws" {
        $result = Test-DockerAvailable -InvokeDockerInfo { throw "command not found" }
        $result | Should -BeFalse
    }
}

Describe "Get-BackupTaskActionArguments" {
    It "wraps the path in double quotes" {
        $args = Get-BackupTaskActionArguments -BackupScriptPath "C:\brain-twin\scripts\backup.ps1"
        $args | Should -Match '"C:\\brain-twin\\scripts\\backup\.ps1"'
    }
    It "quotes a path containing spaces so it stays a single argument" {
        $args = Get-BackupTaskActionArguments -BackupScriptPath "C:\Users\Test User\My Projects\brain-twin\scripts\backup.ps1"
        $args | Should -Match '"C:\\Users\\Test User\\My Projects\\brain-twin\\scripts\\backup\.ps1"'
    }
    It "does not break when the path contains non-ASCII characters" {
        # Built from character codes so this test file itself remains ASCII-only.
        # These four code points spell a common Japanese word for "user".
        $nonAsciiSegment = [string]::new(@([char]0x30E6, [char]0x30FC, [char]0x30B6, [char]0x30FC))
        $path = "C:\$nonAsciiSegment\brain-twin\scripts\backup.ps1"
        $args = Get-BackupTaskActionArguments -BackupScriptPath $path
        $args | Should -Match ([regex]::Escape($nonAsciiSegment))
    }
    It "includes the required PowerShell flags" {
        $args = Get-BackupTaskActionArguments -BackupScriptPath "C:\x\backup.ps1"
        $args | Should -Match "-NoProfile"
        $args | Should -Match "-ExecutionPolicy Bypass"
    }
}
