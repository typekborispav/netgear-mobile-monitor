# Společné pro release-key.ps1 a release.ps1 (PowerShell 7).

Add-Type -AssemblyName System.Security

# Soukromý klíč – jen na tomto počítači, zašifrovaný DPAPI (jen tento účet Windows).
# Záměrně MIMO %APPDATA%\NetgearMonitor (data aplikace).
$KeyFile = Join-Path $env:APPDATA 'NetgearMonitor-release\signing-key.dpapi'
$KeyEntropy = [Text.Encoding]::UTF8.GetBytes('netgear-mobile-monitor release signing key')

function Save-ReleaseKey([byte[]]$pkcs8) {
    New-Item -ItemType Directory -Force (Split-Path $KeyFile) | Out-Null
    $blob = [System.Security.Cryptography.ProtectedData]::Protect($pkcs8, $KeyEntropy,
        [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
    [IO.File]::WriteAllBytes($KeyFile, $blob)
}

function Get-ReleaseKey {
    if (-not (Test-Path $KeyFile)) { throw "chybí podpisový klíč; vytvořte ho: pwsh tools\release-key.ps1 -New" }
    $pkcs8 = [System.Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($KeyFile), $KeyEntropy,
        [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
    $ecdsa = [System.Security.Cryptography.ECDsa]::Create()
    $n = 0
    $ecdsa.ImportPkcs8PrivateKey($pkcs8, [ref]$n)
    return $ecdsa
}

# Přesně tento text ověřuje aplikace (updater.signed_text). Verze a název
# souboru brání vydávat starý podepsaný instalátor za novější.
function Get-SignedText([string]$Version, [string]$FileName, [string]$Sha256) {
    "netgear-mobile-monitor release`nversion=$Version`nfile=$FileName`nsha256=$($Sha256.ToLowerInvariant())`n"
}
