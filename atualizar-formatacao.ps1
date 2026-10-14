param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^[a-f0-9]{40}$')]
    [string]$Ref
)
$ErrorActionPreference = 'Stop'
$crmRoot = (Get-Location).Path
if (-not (Test-Path -LiteralPath (Join-Path $crmRoot '.venv\Scripts\python.exe'))) {
    throw 'Abra o PowerShell na pasta da instalacao existente, onde estao backend, frontend e .venv.'
}
if (Get-NetTCPConnection -LocalPort 3000,8000 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Pare backend e dashboard com Ctrl+C nas duas janelas antes de atualizar. Mantenha Docker aberto.'
}
$crmExpected = @{
    'backend/app/main.py' = '460D602A4D8CC6180AD20D214BD0F401EEDA8BDD9996CAC224D6F659B3D310EC'
    'frontend/app/page.tsx' = 'BCF530E6A1732BC7BAC9A5A544BB17A2B5DD6514E2E09C039DC73EC4EAA9E80A'
    'frontend/app/globals.css' = 'D1902979601F14492FD4438FA50B3D77717E865D0585E513A2765BE02268E736'
    'frontend/app/api/backend/[...path]/route.ts' = '1C5903DAC520684A3E8F578DEF7A9A427702331C3C628F8F36105FD16C991E69'
}
$crmPrivate = Join-Path $crmRoot ('private\updates\' + [guid]::NewGuid().ToString('N'))
$crmStage = Join-Path $crmPrivate 'new'
$crmBackup = Join-Path $crmPrivate 'backup'
[System.IO.Directory]::CreateDirectory($crmStage) | Out-Null
[System.IO.Directory]::CreateDirectory($crmBackup) | Out-Null
foreach ($crmRelative in $crmExpected.Keys) {
    $crmDownload = Join-Path $crmStage ($crmExpected[$crmRelative] + '.download')
    $crmEncodedPath = (($crmRelative -split '/') | ForEach-Object { [uri]::EscapeDataString($_) }) -join '/'
    $crmUrl = 'https://raw.githubusercontent.com/alisonabandono2-tech/telegram/' + $Ref + '/' + $crmEncodedPath
    Invoke-WebRequest -UseBasicParsing -Uri $crmUrl -OutFile $crmDownload -TimeoutSec 60
    if ((Get-FileHash -LiteralPath $crmDownload -Algorithm SHA256).Hash -ne $crmExpected[$crmRelative]) {
        throw 'Verificacao de integridade falhou. Nenhum arquivo da instalacao foi alterado.'
    }
}
foreach ($crmRelative in $crmExpected.Keys) {
    $crmCurrent = Join-Path $crmRoot $crmRelative
    if (-not (Test-Path -LiteralPath $crmCurrent)) { throw ('Arquivo da instalacao nao encontrado: ' + $crmRelative) }
    $crmSaved = Join-Path $crmBackup ($crmExpected[$crmRelative] + '.backup')
    [System.IO.File]::Copy($crmCurrent, $crmSaved, $true)
}
try {
    foreach ($crmRelative in $crmExpected.Keys) {
        $crmSource = Join-Path $crmStage ($crmExpected[$crmRelative] + '.download')
        [System.IO.File]::Copy($crmSource, (Join-Path $crmRoot $crmRelative), $true)
    }
} catch {
    foreach ($crmRelative in $crmExpected.Keys) {
        $crmSaved = Join-Path $crmBackup ($crmExpected[$crmRelative] + '.backup')
        [System.IO.File]::Copy($crmSaved, (Join-Path $crmRoot $crmRelative), $true)
    }
    throw 'Atualizacao nao concluida. Os arquivos copiados foram restaurados da copia de seguranca.'
}
Write-Host 'Atualizacao de formatacao instalada. Configuracoes, sessao e banco foram preservados.'
Write-Host ('Copia de seguranca do codigo: ' + $crmBackup)
Write-Host 'Reinicie backend e dashboard como antes. Depois atualize a pagina do navegador.'
