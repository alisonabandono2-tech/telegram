# Telegram CRM — Auditoria de conversas privadas

Primeira versão para uso local no Windows: Next.js/TypeScript, FastAPI, Telethon (MTProto), PostgreSQL e Pandas/OpenPyXL. Não há envio de mensagens nem resolução de IDs desconhecidos. A auditoria percorre os diálogos disponíveis e cruza usuários privados com os IDs únicos da planilha. Bots e Mensagens Salvas são excluídos. Ausência de correspondência não prova ausência de contato passado: diálogos apagados não podem ser recuperados.

## Windows — instalação

Pré-requisitos: Python 3.12, Node.js 22 ou superior e Docker Desktop (ou PostgreSQL 16 instalado). Use PowerShell na raiz do projeto.

```powershell
$env:POSTGRES_PASSWORD = 'escolha-uma-senha-local-forte'
docker compose up -d postgres
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock.txt
Copy-Item backend\.env.example backend\.env
cd frontend
npm ci
cd ..
```

Edite `backend/.env`: configure DATABASE_URL com a mesma senha do PostgreSQL (codifique caracteres especiais na URL), TELEGRAM_API_ID e TELEGRAM_API_HASH obtidos em https://my.telegram.org, e APP_TOKEN aleatório de pelo menos 24 caracteres. Não coloque o API Hash em variáveis NEXT_PUBLIC. Para gerar um token local: `py -c "import secrets; print(secrets.token_urlsafe(32))"`. A senha 2FA é enviada ao backend local apenas durante o login, não persistida. API Hash, telefone e sessão nunca são retornados pelo backend.

Proteja `backend/private` no Windows: use uma conta Windows individual, BitLocker e permissões NTFS restritas ao seu usuário. O arquivo de sessão permite acesso à conta e deve ser tratado como uma credencial. Não sincronize essa pasta com armazenamento compartilhado. Dados de auditoria ficam no PostgreSQL; proteja também seu volume. As permissões Unix são restringidas automaticamente; no Windows a proteção depende das ACLs da pasta.

## Iniciar

Terminal 1, na raiz:
```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```
Terminal 2, na raiz:
```powershell
cd frontend
npm run dev
```
Abra o dashboard local na porta 3000. Informe APP_TOKEN, conecte ao sistema, solicite código pelo telefone e finalize código/2FA. Importe `inscritos_todos.xlsx`. A detecção reconhece ID, Telegram ID, User ID, ID Telegram ou ID Usuario; se houver ambiguidade, informe o nome exato da coluna. Limite de upload: 10 MB. Duplicatas e linhas inválidas são contabilizadas separadamente. Os indicadores com/sem username consideram apenas os membros encontrados. Exportações CSV/XLSX incluem todos os IDs válidos únicos e protegem células contra fórmulas.

Execute apenas um worker do backend: o estado de login, a sessão e o progresso são locais ao processo. Uma operação Telegram por vez. Em caso de código expirado reinicie o login. Se uma sessão for revogada e o login não puder ser retomado, pare o backend, remova apenas `backend/private/account.session` e seus arquivos auxiliares, reinicie e autentique novamente. Em caso de FloodWait aguarde o intervalo informado pela API; não há contorno nem repetição agressiva. Os endpoints são protegidos por APP_TOKEN, exceto /health; mantenha os serviços vinculados ao loopback. Esta versão é para uso local individual, não implantação pública ou multiusuário. Use HTTPS se adaptar para acesso remoto.

## Verificação
```powershell
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m pytest backend\tests -q
cd frontend
npm run typecheck
npm run build
```
No Linux: `PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q`. No PowerShell, antes dos testes, defina `$env:PYTHONPATH = 'backend'`.

A planilha real foi analisada: 8.589 linhas e 8.589 IDs únicos válidos na coluna `ID`, sem duplicatas ou linhas inválidas. As demais colunas são `Nome`, `@usuario` e `Abrir conversa`. Elas não são usadas para resolver usuários; os dados de nome e username apresentados vêm dos diálogos da conta. Os testes usam dados fictícios. Login real, leitura MTProto, correspondência dos 8.589 membros e exportações com seus dados dependem das credenciais e da autenticação da conta. A aplicação não infere autorização para publicidade.
