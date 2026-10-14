# Telegram CRM — Contatos e auditoria

Aplicação local para Windows com Next.js/TypeScript, FastAPI, Telethon (API MTProto oficial), PostgreSQL e Pandas/OpenPyXL. A página principal é uma tela simples de envio **individual e manual pela conta pessoal**, sem bot e sem token de bot. A auditoria anterior continua disponível em `/auditoria` e permanece exclusivamente de leitura.

## Tela principal

- Login com telefone, código do Telegram e senha 2FA quando necessária.
- Importação XLSX ou CSV com `Nome` e `@usuario`/`username`; nome é opcional. Se houver `ID`, o sistema confirma que o username ainda pertence a esse ID antes de enviar.
- Apenas contatos com username válido entram na lista. A planilha fornecida contém 1.427 usernames com formato válido entre 8.589 registros; a existência dos perfis depende da verificação real no Telegram.
- Busca, filtros de pendentes/enviados/bloqueados, seleção de destinatário e contador de enviados.
- **Excluir contato**: confirmação antes de remover da lista. Não altera o Telegram. A exclusão fica no banco e impede reimportação por username ou ID conhecido, preservando os registros de envios. Contatos com o mesmo ID conhecido são excluídos juntos. Não há restauração na interface nesta versão.
- Mensagem editável com `{nome}` e prévia; PNG/JPEG até 5 MB e 20 megapixels. Máximo de 4.096 caracteres em texto ou 1.024 com imagem.
- Um envio por clique após confirmação de destinatário, conteúdo e autorização para essa comunicação. Importação não presume consentimento. Próximo contato não envia nada.
- Histórico de status persistido, bloqueio de contatos, prevenção de cliques duplicados e impedimento de novo envio a contatos já marcados como enviados.
- Intervalo mínimo local de 10 segundos, sem fila, agendamento, rodízio de contas ou tentativas automáticas. FloodWait do Telegram é respeitado e persistido; PeerFlood suspende o sistema por pelo menos 24 horas e exige avaliar a conta. Esses intervalos não garantem ausência de restrições ou suspensão.
- Se a conexão cair durante um envio, o resultado fica **incerto**; confira a conversa no Telegram. O sistema não reenvia automaticamente e bloqueia repetição ao mesmo contato.

Não use contatos sem autorização para comunicação. Um username público ou participação em grupo não estabelece consentimento. Esta versão não foi validada com uma conta real e não oferece garantia contra restrições do Telegram.

## Windows — instalar

Pré-requisitos: Python 3.12, Node.js 22 ou superior, Docker Desktop em execução (ou PostgreSQL 16 próprio). Abra PowerShell na pasta que contém `backend`, `frontend` e `compose.yaml`.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\configurar-local.ps1
docker compose up -d postgres
docker compose exec -T postgres pg_isready -U crm -d telegram_crm
cd frontend
npm.cmd ci
cd ..
```

`configurar-local.ps1` cria a senha do banco em `.env` somente se esse arquivo não existir. Cria `backend/.env` somente se ausente e transfere exclusivamente o token interno APP_TOKEN para `frontend/.env.local`. Preserva arquivos existentes; se detectar um token diferente no frontend, para para evitar sobrescrita. Nunca mostra credenciais. `-ExecutionPolicy Bypass` se aplica somente ao processo que executa o script local revisável; não modifica a política permanente do Windows.

Obtenha API ID e API Hash em https://my.telegram.org > API development tools. Edite **apenas** `TELEGRAM_API_ID` e `TELEGRAM_API_HASH` em `backend/.env`, preservando DATABASE_URL e APP_TOKEN gerados. Esses dois campos continuam necessários para clientes pessoais Telegram; não são tokens de bot. A senha 2FA é informada no dashboard durante o login e não é persistida.

O token interno do aplicativo não precisa ser digitado na nova tela: o servidor Next o usa para falar com o backend. Não coloque esse token nem API Hash em variáveis `NEXT_PUBLIC_*`. O frontend navegador não recebe API Hash ou arquivos de sessão. O proxy local rejeita origens externas, limita upload e só encaminha as rotas do aplicativo para o backend fixo de loopback.

## Windows — atualizar uma instalação existente

Pare backend/dashboard que você iniciou com Ctrl+C. Extraia o ZIP novo em outra pasta. Copie apenas os arquivos do projeto atualizado para a pasta existente, substituindo o código correspondente. **Preserve** `.venv`, `.env`, `backend/.env`, `backend/private` e dados do PostgreSQL; esses arquivos não estão no ZIP. Depois execute novamente a instalação de requirements.lock.txt, `configurar-local.ps1` e `npm.cmd ci`. Não use `docker compose down -v`: isso apaga o volume do banco.

## Iniciar

Terminal 1, na raiz:
```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Terminal 2, na raiz:
```powershell
cd frontend
npm.cmd run dev
```

Abra o dashboard local na porta 3000. Conecte sua conta com telefone/código/2FA, importe a planilha, escolha um contato, edite a mensagem, anexe uma imagem opcional e confira a prévia. Confirme autorização e clique em **Enviar para este contato**. Por padrão, mensagens são enviadas como texto literal. Para negrito/itálico, marque **Usar formatação (negrito/itálico)**, selecione um trecho na mensagem e clique em **Negrito** ou **Itálico**. A prévia mostra o resultado para o contato escolhido. Também é possível escrever `<b>Olá {nome}</b>` com essa opção ativada. São aceitas marcações HTML simples `b`, `strong`, `i`, `em`, `u`, `s`, `del`, `code` e `pre`, sem atributos; Markdown não é interpretado. `{nome}` continua sendo substituído, com caracteres especiais escapados na formatação. Os limites de 4096 caracteres sem imagem e 1024 na legenda consideram o texto visível (UTF-16), sem contar as marcações. **Próximo contato** somente troca a seleção.

Use um único worker do backend e uma única instância local. Mantenha os serviços em loopback. O dashboard deve usar a porta 3000. Esta versão é para uso local individual, não implantação pública ou multiusuário. Proteja banco e arquivos da sessão com conta Windows individual, ACLs NTFS e criptografia de disco; não compartilhe `backend/private`. Sessões Unix têm permissões restritas automaticamente. Uma sessão equivale a acesso à conta.

Se um código expirar, reinicie o login no dashboard. Se a sessão for revogada e o login não puder ser retomado, pare o backend, remova apenas os arquivos `backend/private/account.session*`, reinicie e autentique novamente. Não remova a sessão com o backend rodando.

## Auditoria anterior

Em `/auditoria`, informe o APP_TOKEN local quando solicitado. Importe os IDs e percorra apenas os diálogos disponíveis, sem enviar mensagens. Bots, grupos e Mensagens Salvas são excluídos. Nome e username vêm dos diálogos; a última interação é a data da última mensagem disponível, não necessariamente uma mensagem enviada pelo titular. Ausência de correspondência não prova inexistência de contato anterior: diálogos apagados não são recuperados. Exportações CSV/XLSX neutralizam fórmulas.

## Testes

```powershell
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m pytest backend\tests -q
cd frontend
npm.cmd run typecheck
npm.cmd run build
```

Os testes usam Telethon simulado e SQLite por padrão. Para PostgreSQL, defina TEST_DATABASE_URL de um banco **dedicado e descartável**: as fixtures apagam as tabelas que criam. Nunca use um banco com dados reais nesses testes.

Há também teste de navegador em `frontend/tests/browser-smoke.cjs` e backend fictício em `backend/tests/browser_server.py`. O servidor fictício é exclusivo de testes: não se conecta ao Telegram. Para reproduzir o teste, instale Playwright separadamente (por exemplo, em uma pasta temporária), execute browser_server.py, inicie Next com APP_TOKEN `fictional-token-for-tests-only-1234`, defina NODE_PATH para a instalação de Playwright, CHROMIUM_PATH para um Chromium instalado e TEST_IMAGE_BASE64 com um PNG fictício, e execute `node frontend/tests/browser-smoke.cjs`. Pare esses processos após o teste; nunca use o servidor fictício para contatos reais.

Consulte VALIDATION.md para evidências e limitações. Autenticação, resolução de usernames e envio reais exigem as credenciais e a conta do usuário; nenhuma mensagem real foi enviada durante o desenvolvimento.

## Atualizar apenas o botão de exclusão

O helper `atualizar-exclusao.ps1 -Ref <SHA completo da versão>` atualiza apenas quatro arquivos de código. Execute na raiz da instalação, depois de parar backend e dashboard com Ctrl+C; mantenha Docker funcionando. O helper exige as portas 3000/8000 livres, baixa arquivos da revisão exata, verifica SHA256 de todos antes de substituir qualquer um, cria backup em `private/updates` e preserva .env, sessão, dependências e banco. Ele não foi executado em Windows durante desenvolvimento; se falhar, os backups de código ficam disponíveis. Não são necessárias migrações ou novas dependências para essa atualização. Reinicie os dois serviços e atualize a página depois.
