param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('export', 'import')]
    [string]$Mode,

    [string]$OutFile,
    [string]$InFile,
    [string]$PresetRoot,
    [string]$Key,
    [string]$Label,
    [string]$Scope,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

function Write-JsonUtf8 {
    param(
        [Parameter(Mandatory = $true)] $InputObject,
        [Parameter(Mandatory = $true)] [string]$Path
    )
    $json = $InputObject | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText($Path, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Read-JsonFile {
    param([Parameter(Mandatory = $true)] [string]$Path)
    $raw = [System.IO.File]::ReadAllText($Path)
    return $raw | ConvertFrom-Json
}

if ($Mode -eq 'export') {
    if (-not $OutFile) { throw 'Missing OutFile' }
    if (-not $Key) { throw 'Missing Key' }
    if (-not $Label) { throw 'Missing Label' }
    if (-not $Scope) { throw 'Missing Scope' }

    $payload = [pscustomobject]@{
        key        = $Key
        label      = $Label
        scope      = $Scope
        updated_at = (Get-Date).ToString('o')
    }
    Write-JsonUtf8 -InputObject $payload -Path $OutFile
    exit 0
}

if ($Mode -eq 'import') {
    if (-not $InFile) { throw 'Missing InFile' }
    if (-not $PresetRoot) { throw 'Missing PresetRoot' }
    if (-not (Test-Path -LiteralPath $InFile)) { throw "File not found: $InFile" }

    $payload = Read-JsonFile -Path $InFile
    if (-not $payload.key) { throw 'JSON missing key' }
    if (-not $payload.label) { throw 'JSON missing label' }
    if (-not $payload.scope) { throw 'JSON missing scope' }

    $key = [string]$payload.key
    $label = [string]$payload.label
    $scope = [string]$payload.scope
    $targetDir = Join-Path $PresetRoot $key

    if (Test-Path -LiteralPath $targetDir) {
        if (-not $Force) {
            throw "Preset exists: $key"
        }
        Remove-Item -LiteralPath $targetDir -Recurse -Force
    }

    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $targetDir 'label.txt'), $label, (New-Object System.Text.UTF8Encoding($false)))
    [System.IO.File]::WriteAllText((Join-Path $targetDir 'scope.txt'), $scope, (New-Object System.Text.UTF8Encoding($false)))

    Write-Output "key=$key"
    Write-Output "label=$label"
    Write-Output "scope=$scope"
    exit 0
}
