# Validação — contatos individuais e auditoria

- Planilha fornecida: 8.589 IDs únicos válidos, coluna ID, sem duplicatas ou IDs inválidos. Para a tela de contatos, 1.427 usernames com formato válido e 7.162 linhas sem username válido; existência desses perfis ainda não validada no Telegram. Dados pessoais não foram adicionados ao repositório.
- 15 testes passaram em SQLite e PostgreSQL 16 real. Auditoria cobre importação, IDs grandes, ambiguidade, comparação, login/2FA, autenticação, FloodWait, persistência e exportação. Contatos cobre importação repetível, exclusão de linhas sem username, envio único e prevenção de duplicatas, cooldown, confirmação, bloqueio, ID divergente, imagem/caption, privacidade e resultado incerto após perda de conexão.
- Teste de navegador Chromium com Next e FastAPI reais, usando Telethon simulado: login/código/2FA, importação CSV, busca, seleção, personalização `{nome}`, prévia PNG, confirmação, um envio simulado, próximo contato, bloqueio, proteção de origem e viewport mobile passaram. O teste verificou que o outro contato permaneceu pendente e que não houve erros JavaScript.
- Next.js 16.4.0: build de produção e TypeScript passaram. Proxy mantém APP_TOKEN no servidor e não exige token de bot no dashboard. A auditoria continua em `/auditoria`.
- Os processos de teste não se conectaram ao Telegram real. O servidor fictício está em backend/tests/browser_server.py e não participa do startup normal.
- A execução desta versão foi feita em Linux. O usuário já conseguiu instalar as dependências Python/frontend e iniciar PostgreSQL no Windows; o login e envio da nova versão no Windows ainda estão pendentes.

Não houve autenticação real, resolução real de usernames, leitura real de diálogos ou envio de mensagens. Essas operações dependem de API ID/API Hash e da conta do usuário. A disponibilidade de usernames, permissões e limites de envio é determinada pelo Telegram. Enviar lentamente não elimina risco de limitações ou suspensão.

Há um aviso de depreciação da integração Starlette/AnyIO nos testes, sem falhas. O download de um Chromium adicional foi bloqueado pela política de rede; o teste de navegador foi concluído usando /usr/bin/chromium já instalado, sem alterar a política nem desabilitar TLS.
