<#
.SYNOPSIS
    Správa klíče, kterým se podepisují vydání Netgear Mobile Monitor.

.DESCRIPTION
    Aplikace nainstaluje aktualizaci jen s podpisem tímto klíčem, takže ani
    převzatý GitHub účet nebo build nepodstrčí uživatelům falešnou verzi.
    Soukromý klíč nikdy neopustí tento počítač: je uložený zašifrovaný přes
    Windows DPAPI (použitelný jen pod tímto účtem Windows).

      -New               vytvoří klíč (existující nepřepíše)
      -Public            vypíše veřejný klíč (patří do updater.py, SIGNING_KEY)
      -Backup <soubor>   záloha klíče zašifrovaná heslem, které zadáte
      -Restore <soubor>  obnova zálohy na novém počítači

    Ztráta klíče = nainstalované kopie se už samy neaktualizují (další verzi
    by bylo nutné stáhnout ručně). Udělejte si zálohu.

    Vyžaduje PowerShell 7 (pwsh).
#>
param(
    [switch]$New,
    [switch]$Public,
    [string]$Backup,
    [string]$Restore
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'release-common.ps1')

if ($New) {
    if (Test-Path $KeyFile) { throw "klíč už existuje: $KeyFile" }
    $ecdsa = [System.Security.Cryptography.ECDsa]::Create([System.Security.Cryptography.ECCurve+NamedCurves]::nistP256)
    Save-ReleaseKey $ecdsa.ExportPkcs8PrivateKey()
    "vytvořen $KeyFile"
    "veřejný klíč: " + [Convert]::ToBase64String($ecdsa.ExportSubjectPublicKeyInfo())
}
elseif ($Public) {
    [Convert]::ToBase64String((Get-ReleaseKey).ExportSubjectPublicKeyInfo())
}
elseif ($Backup) {
    $pw = Read-Host "Heslo pro zálohu" -AsSecureString
    $pw2 = Read-Host "Znovu" -AsSecureString
    $a = [System.Net.NetworkCredential]::new('', $pw).Password
    if ($a -ne [System.Net.NetworkCredential]::new('', $pw2).Password) { throw "hesla se liší" }
    if ($a.Length -lt 12) { throw "použijte aspoň 12 znaků" }
    $pbe = [System.Security.Cryptography.PbeParameters]::new(
        [System.Security.Cryptography.PbeEncryptionAlgorithm]::Aes256Cbc,
        [System.Security.Cryptography.HashAlgorithmName]::SHA256, 600000)
    $pem = (Get-ReleaseKey).ExportEncryptedPkcs8PrivateKeyPem($a, $pbe)
    Set-Content -LiteralPath $Backup -Value $pem -Encoding ascii
    "záloha uložena do $Backup"
}
elseif ($Restore) {
    if (Test-Path $KeyFile) { throw "klíč už existuje: $KeyFile" }
    $pw = Read-Host "Heslo zálohy" -AsSecureString
    $ecdsa = [System.Security.Cryptography.ECDsa]::Create()
    $ecdsa.ImportFromEncryptedPem((Get-Content -LiteralPath $Restore -Raw),
        [System.Net.NetworkCredential]::new('', $pw).Password)
    Save-ReleaseKey $ecdsa.ExportPkcs8PrivateKey()
    "obnoveno do $KeyFile"
}
else {
    Get-Help $PSCommandPath -Detailed
}
