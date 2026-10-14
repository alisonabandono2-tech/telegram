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
    'backend/app/main.py' = '4B1DB0843944C833AD91E1F578169A04DDB3BC914CF2CDD9CC1DC256A615DE2F'
    'frontend/app/page.tsx' = '46927EB86E85288983817081B3972A174D6B6873667C11B586A40222BE73629E'
    'frontend/app/globals.css' = '4BC132EA482C1BCD4A2E989146D47C4D73A01176DB08375CF47E69BA5BBE0700'
    'frontend/app/api/backend/[...path]/route.ts' = '1C5903DAC520684A3E8F578DEF7A9A427702331C3C628F8F36105FD16C991E69'
}
$crmPrivate = Join-Path $crmRoot ('private\updates\' + [guid]::NewGuid().ToString('N'))
$crmStage = Join-Path $crmPrivate 'new'
$crmBackup = Join-Path $crmPrivate 'backup'
$crmUpdated = @()
foreach ($crmRelative in $crmExpected.Keys) {
    $crmDownload = Join-Path $crmStage $crmRelative
    New-Item -ItemType Directory -Path (Split-Path -Parent $crmDownload) -Force | Out-Null
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
    $crmSaved = Join-Path $crmBackup $crmRelative
    New-Item -ItemType Directory -Path (Split-Path -Parent $crmSaved) -Force | Out-Null
    Copy-Item -LiteralPath $crmCurrent -Destination $crmSaved -Force
}
try {
    foreach ($crmRelative in $crmExpected.Keys) {
        Copy-Item -LiteralPath (Join-Path $crmStage $crmRelative) -Destination (Join-Path $crmRoot $crmRelative) -Force
        $crmUpdated += $crmRelative
    }
} catch {
    foreach ($crmRelative in $crmExpected.Keys) {
        Copy-Item -LiteralPath (Join-Path $crmBackup $crmRelative) -Destination (Join-Path $crmRoot $crmRelative) -Force
    }
    throw 'Atualizacao nao concluida. Os arquivos copiados foram restaurados da copia de seguranca.'
}
Write-Host 'Atualizacao de exclusao instalada. Configuracoes, sessao e banco foram preservados.'
Write-Host ('Copia de seguranca do codigo: ' + $crmBackup)
Write-Host 'Reinicie backend e dashboard como antes. Depois atualize a pagina do navegador.'
