$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
@'
from pathlib import Path
import secrets
from dotenv import dotenv_values
root = Path('.env')
if not root.exists():
    root.write_text('POSTGRES_PASSWORD=' + secrets.token_hex(24) + '\n', encoding='utf-8')
backend = Path('backend/.env')
if not backend.exists():
    password = dotenv_values(root)['POSTGRES_PASSWORD']
    template = Path('backend/.env.example').read_text()
    template = template.replace('crm_local', password).replace('substitua_por_um_token_aleatorio_de_32_caracteres', secrets.token_urlsafe(32))
    backend.write_text(template, encoding='utf-8')
token = dotenv_values(backend).get('APP_TOKEN')
if not token or len(token) < 24:
    raise SystemExit('Configure APP_TOKEN no backend antes de continuar.')
frontend = Path('frontend/.env.local')
if frontend.exists():
    values = dotenv_values(frontend)
    if values.get('APP_TOKEN') != token:
        raise SystemExit('frontend/.env.local ja existe com outra configuracao. Nao foi sobrescrito.')
else:
    frontend.write_text('APP_TOKEN=' + token + '\n', encoding='utf-8')
print('Configuracao local pronta. Nenhuma credencial foi exibida.')
'@ | .\.venv\Scripts\python.exe -
if ($LASTEXITCODE -ne 0) { throw 'Configuracao nao concluida.' }
