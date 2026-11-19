<#
.SYNOPSIS
    Sestaví, podepíše a zveřejní vydání Netgear Mobile Monitor z tohoto počítače.

.DESCRIPTION
    1. kontrola: čistý pracovní strom, větev main, tag ještě neexistuje,
       version.py má stejnou verzi jako -Version, klíč sedí na SIGNING_KEY
    2. sestavení instalátoru (build.ps1)
    3. podpis klíčem (tools\release-key.ps1) a kontrola podpisu .NET i
       samotnou aplikací (updater.verify_signature)
    4. tag vX.Y.Z, push a GitHub Release s instalátorem, .sig a .sha256

    Sestavuje se tady, ne na GitHubu: převzatý GitHub účet ani build tak
    nezíská podpis pro kód, který jste sami nesestavili.

.EXAMPLE
    pwsh tools\release.ps1 -Version 2.5.0
    pwsh tools\release.ps1 -Version 2.5.0 -NotesFile notes.md
#>
param(
    [Parameter(Mandatory)][string]$Version,
    [string]$NotesFile,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'release-common.ps1')
$root = Split-Path $PSScriptRoot
Push-Location $root
try {
    if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "verze musí vypadat jako 1.2.3" }
    $tag = "v$Version"

    # ---------------------------------------------------------- kontroly
    if (-not $DryRun) {
        if (git status --porcelain) { throw "necommitnuté změny; nejdřív commit" }
        if ((git rev-parse --abbrev-ref HEAD) -ne 'main') { throw "nejste na větvi main" }
    }
    if (git tag --list $tag) { throw "tag $tag už existuje" }
    $pyVersion = (python -c "import version; print(version.__version__)").Trim()
    if ($pyVersion -ne $Version) { throw "version.py má verzi $pyVersion" }
    $updater = Get-Content updater.py -Raw
    if ($updater -notmatch 'SIGNING_KEY\s*=\s*"([A-Za-z0-9+/=]+)"') { throw "SIGNING_KEY v updater.py nenalezen" }
    $appKey = $Matches[1]
    $key = Get-ReleaseKey
    if ([Convert]::ToBase64String($key.ExportSubjectPublicKeyInfo()) -ne $appKey) {
        throw "podpisový klíč nesedí na SIGNING_KEY v updater.py"
    }

    # ---------------------------------------------------------- sestavení
    powershell -ExecutionPolicy Bypass -File .\build.ps1
    if ($LASTEXITCODE -ne 0) { throw "build.ps1 selhal" }
    $exe = Get-Item "dist\NetgearMonitor-Setup-$Version.exe"

    # ---------------------------------------------------------- podpis
    $sha = (Get-FileHash $exe.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    $text = [Text.Encoding]::UTF8.GetBytes((Get-SignedText $Version $exe.Name $sha))
    $sig = $key.SignData($text, [System.Security.Cryptography.HashAlgorithmName]::SHA256,
        [System.Security.Cryptography.DSASignatureFormat]::IeeeP1363FixedFieldConcatenation)
    $check = [System.Security.Cryptography.ECDsa]::Create()
    $n = 0
    $check.ImportSubjectPublicKeyInfo([Convert]::FromBase64String($appKey), [ref]$n)
    if (-not $check.VerifyData($text, $sig, [System.Security.Cryptography.HashAlgorithmName]::SHA256,
            [System.Security.Cryptography.DSASignatureFormat]::IeeeP1363FixedFieldConcatenation)) {
        throw "podpis nesedí (.NET)"
    }
    $sigFile = "$($exe.FullName).sig"
    Set-Content -LiteralPath $sigFile -Value ([Convert]::ToBase64String($sig)) -Encoding ascii -NoNewline

    # stejnou kontrolou jako aplikace (Windows CNG v updater.py)
    $env:NGMM_SIG_EXE = $exe.FullName
    $env:NGMM_SIG_VER = $Version
    python -c "import os, base64, hashlib, updater as u; p=os.environ['NGMM_SIG_EXE']; s=base64.b64decode(open(p+'.sig').read()); h=hashlib.sha256(open(p,'rb').read()).hexdigest(); t=u.signed_text(os.environ['NGMM_SIG_VER'], os.path.basename(p), h).encode(); raise SystemExit(0 if u.verify_signature(t, s) else 1)"
    if ($LASTEXITCODE -ne 0) { throw "podpis nesedí (updater.py)" }
    "podepsáno: $($exe.Name)  sha256 $sha"

    if ($DryRun) { "zkouška: bez tagu a zveřejnění"; return }

    # ---------------------------------------------------------- zveřejnění
    git tag -a $tag -m "Netgear Mobile Monitor $Version"
    git push origin main $tag
    if ($LASTEXITCODE -ne 0) { throw "git push selhal" }
    $notes = if ($NotesFile) { @('--notes-file', $NotesFile) } else { @('--generate-notes') }
    gh release create $tag $exe.FullName $sigFile "$($exe.FullName).sha256" `
        --title "Netgear Mobile Monitor $tag" @notes
    if ($LASTEXITCODE -ne 0) { throw "gh release create selhal" }
    "zveřejněno $tag"
}
finally {
    Pop-Location
}
