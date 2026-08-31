param(
    [Parameter(Mandatory = $true)]
    [string]$Key,

    [string]$Name = "",

    [AllowEmptyString()]
    [string]$Description = "",

    [ValidateSet('auto', 'general', 'scan', 'post', 'auth', 'backup')]
    [string]$Profile = 'auto',

    [switch]$Force
)

$ErrorActionPreference = 'Stop'

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)] [string]$Path,
        [Parameter(Mandatory = $true)] [string]$Text
    )
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

function Normalize-OneLine {
    param([string]$Value = "")
    $value = $Value -replace "`r", ' '
    $value = $value -replace "`n", ' '
    return $value.Trim()
}

function Get-ShortDescription {
    param(
        [Parameter(Mandatory = $true)] [string]$DisplayName,
        [string]$SourceDescription = ""
    )

    $text = Normalize-OneLine $SourceDescription
    if ($text.Length -lt 25) {
        $text = "$DisplayName helper for testing workflows"
    }
    if ($text.Length -lt 25) {
        $text = "$DisplayName skill for workflow testing"
    }
    if ($text.Length -gt 64) {
        $text = $text.Substring(0, 64).TrimEnd()
    }
    if ($text.Length -lt 25) {
        $text = "$text workflow"
        if ($text.Length -gt 64) {
            $text = $text.Substring(0, 64).TrimEnd()
        }
    }
    return $text
}

function Get-DefaultPrompt {
    param(
        [Parameter(Mandatory = $true)] [string]$DisplayName,
        [Parameter(Mandatory = $true)] [string]$Key,
        [string]$SourceDescription = ""
    )

    $text = ($DisplayName + " " + $Key + " " + $SourceDescription).ToLowerInvariant()

    if ($text -match 'backup|restore|checkpoint|rollback') {
        return "Use $DisplayName to back up, restore, and validate skill changes safely."
    }
    if ($text -match 'export|import|json|yaml|config') {
        return "Use $DisplayName to export, import, and validate structured files."
    }
    if ($text -match 'scan|crawl|scrape|collect') {
        return "Use $DisplayName to scan targets, collect data, and report results clearly."
    }
    if ($text -match 'page|fanpage|account') {
        return "Use $DisplayName to manage account and page workflows with clear validation."
    }
    if ($text -match 'video') {
        return "Use $DisplayName to handle video workflows with careful validation."
    }
    if ($text -match 'photo|image|picture') {
        return "Use $DisplayName to handle photo and image workflows carefully."
    }
    if ($text -match 'post|publish|upload') {
        return "Use $DisplayName to plan, test, and refine posting workflows."
    }
    if ($text -match 'download|media') {
        return "Use $DisplayName to handle download and media workflows safely."
    }
    if ($text -match 'token|auth|login|session|cookie|profile') {
        return "Use $DisplayName to manage authentication, session, and token workflows."
    }
    if ($text -match 'browser|chrome|tab|cdp|playwright') {
        return "Use $DisplayName to work with browser automation safely and predictably."
    }
    return "Use $DisplayName to build and test this skill end to end."
}

function Get-SkillProfile {
    param(
        [Parameter(Mandatory = $true)] [string]$Key,
        [Parameter(Mandatory = $true)] [string]$Name,
        [string]$Description = "",
        [Parameter(Mandatory = $true)] [string]$ProfileName
    )

    $profile = $ProfileName.ToLowerInvariant()
    if ($profile -eq 'auto') {
        $text = ($Key + ' ' + $Name + ' ' + $Description).ToLowerInvariant()
        if ($text -match 'scan|crawl|scrape|collect') { $profile = 'scan' }
        elseif ($text -match 'post|publish|upload') { $profile = 'post' }
        elseif ($text -match 'token|auth|login|session|cookie|profile') { $profile = 'auth' }
        elseif ($text -match 'backup|restore|checkpoint|rollback') { $profile = 'backup' }
        else { $profile = 'general' }
    }

    switch ($profile) {
        'scan' {
            return @{
                Profile = 'scan'
                Goal = '- Quet, phat hien, va bao cao ket qua ro rang.'
                Workflow = @(
                    '1. Xac dinh target can quet.',
                    '2. Mo dung runtime/profile co san neu can.',
                    '3. Quet toi thieu 1 case co lap.',
                    '4. Ghi ro ket qua va canh bao neu co.'
                )
                Guardrails = @(
                    '- Khong doi sang luong browser khac neu khong can.',
                    '- Neu co fail, ghi ly do va diem dung ro rang.'
                )
            }
        }
        'post' {
            return @{
                Profile = 'post'
                Goal = '- Dang, len lich, va kiem tra luong post an toan.'
                Workflow = @(
                    '1. Xac dinh account/page/target duoc phep dang.',
                    '2. Thu truoc voi case nho hoac API neu co.',
                    '3. Ghi ro trang thai thanh cong / that bai.',
                    '4. Neu co scheduling, test mot job rieng.'
                )
                Guardrails = @(
                    '- Khong lam mat session dang dung.',
                    '- Uu tien flow that ro rang hon flow mau me.'
                )
            }
        }
        'auth' {
            return @{
                Profile = 'auth'
                Goal = '- Quan ly session, token, cookie, va profile dang nhap.'
                Workflow = @(
                    '1. Xac minh session/profile hien co.',
                    '2. Kiem tra token/cookie con song hay khong.',
                    '3. Luu ket qua va ly do het han neu co.',
                    '4. Test tren 1 account truoc khi mo rong.'
                )
                Guardrails = @(
                    '- Khong luu thong tin nhay cam khong can thiet.',
                    '- Neu token loi, ghi ro subcode / message neu co.'
                )
            }
        }
        'backup' {
            return @{
                Profile = 'backup'
                Goal = '- Tao checkpoint, backup, va restore nhanh khi thu nghiem.'
                Workflow = @(
                    '1. Xac dinh file scope can theo doi.',
                    '2. Test 1 thay doi nho moi lan.',
                    '3. Tao checkpoint khi on.',
                    '4. Restore ngay neu co loi.'
                )
                Guardrails = @(
                    '- Khong gop qua nhieu thay doi trong 1 lan.',
                    '- Ghi ro branch / commit / scope khi backup.'
                )
            }
        }
        default {
            return @{
                Profile = 'general'
                Goal = '- Tap trung vao 1 nhiem vu ro rang.'
                Workflow = @(
                    '1. Xac dinh runtime files can sua.',
                    '2. Sua 1 y tuong nho moi lan.',
                    '3. Test 1 case co lap.',
                    '4. Tao checkpoint neu on.'
                )
                Guardrails = @(
                    '- Khong dung du lieu runtime o day neu khong can.',
                    '- Cap nhat SKILL.md sau moi thay doi hanh vi dang ke.'
                )
            }
        }
    }
}

$scriptRoot = $PSScriptRoot
if (-not $scriptRoot) {
    $scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$repoRoot = Split-Path -Parent $scriptRoot
$SkillRoot = Join-Path $repoRoot '.agent\skills'

$key = Normalize-OneLine $Key
$name = Normalize-OneLine $Name
$description = Normalize-OneLine $Description
if (-not $key) { throw 'Missing Key' }
if (-not $name) { $name = $key }
if (-not $description) { $description = "" }

$targetDir = Join-Path $SkillRoot $key
if (Test-Path -LiteralPath $targetDir) {
    if (-not $Force) {
        throw "Skill exists: $key"
    }
    $null = & cmd /c "rmdir /s /q `"$targetDir`""
}

New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

$displayName = $name
$shortDescription = Get-ShortDescription -DisplayName $displayName -SourceDescription $description
$defaultPrompt = Get-DefaultPrompt -DisplayName $displayName -Key $key -SourceDescription $description
$skillProfile = Get-SkillProfile -Key $key -Name $displayName -Description $description -ProfileName $Profile

$skillMdTemplate = @'
---
name: {0}
description: {1}
---

# {0}

## Muc tieu

{3}

## Runtime files

- `core/{2}.py`
- `gui/{2}.py`

## Workflow

{4}

## Guardrails

{5}
'@
$skillMd = $skillMdTemplate -f $name, $description, $key, $skillProfile.Goal, ($skillProfile.Workflow -join "`n"), ($skillProfile.Guardrails -join "`n")

Write-Utf8NoBom -Path (Join-Path $targetDir 'SKILL.md') -Text $skillMd

$readmeTemplate = @'
# {0}

Skill nay duoc tao tu template de dung cho thu nghiem va mo rong.

## Profile

- {2}

## Muc tieu

- {3}
- Test tung y tuong nho, de rollback nhanh.
- Uu tien runtime files hon tai lieu dai dong.

## Runtime files

- `core/{1}.py`
- `gui/{1}.py`

## Quick start

1. Sua `SKILL.md` truoc neu hanh vi thay doi dang ke.
2. Chinh `core/{1}.py` hoac `gui/{1}.py` tuy phan viec.
3. Tao checkpoint sau moi lan test on.
4. Dung `_Skill tools\skill-tools.bat` de backup / restore nhanh.

## Note

Day la skill reference cho phat trien va debug. Khong load runtime tu `.agent/skills` trong app.
'@
$readme = $readmeTemplate -f $displayName, $key, $skillProfile.Profile, $skillProfile.Goal.TrimStart('-').Trim()
Write-Utf8NoBom -Path (Join-Path $targetDir 'README.md') -Text $readme

$agentsDir = Join-Path $targetDir 'agents'
New-Item -ItemType Directory -Path $agentsDir -Force | Out-Null

$assetsDir = Join-Path $targetDir 'assets'
New-Item -ItemType Directory -Path $assetsDir -Force | Out-Null
if (-not $shortDescription) {
    $shortDescription = "$displayName helper for testing workflows"
}
$openAiPath = Join-Path $agentsDir 'openai.yaml'
$openAiText = @"
interface:
  display_name: $displayName
  short_description: $shortDescription
  default_prompt: $defaultPrompt
"@
Write-Utf8NoBom -Path $openAiPath -Text $openAiText

$coreDir = Join-Path $targetDir 'core'
$guiDir = Join-Path $targetDir 'gui'
New-Item -ItemType Directory -Path $coreDir -Force | Out-Null
New-Item -ItemType Directory -Path $guiDir -Force | Out-Null

$coreStub = @"
"""
Core runtime stub for $displayName.

Replace this file with the real runtime implementation when you are ready.
"""

SKILL_NAME = "$displayName"


def main():
    raise NotImplementedError("Implement $displayName core runtime here")


if __name__ == "__main__":
    main()
"@
Write-Utf8NoBom -Path (Join-Path $coreDir "$key.py") -Text $coreStub

$guiStub = @"
"""
GUI runtime stub for $displayName.

Replace this file with the real GUI integration when you are ready.
"""

SKILL_NAME = "$displayName"


def main():
    raise NotImplementedError("Implement $displayName GUI runtime here")


if __name__ == "__main__":
    main()
"@
Write-Utf8NoBom -Path (Join-Path $guiDir "$key.py") -Text $guiStub

Write-Output "key=$key"
Write-Output "name=$name"
Write-Output "description=$description"
