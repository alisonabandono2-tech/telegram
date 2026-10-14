# Validação — contatos individuais e auditoria

- Planilha fornecida: 8.589 IDs únicos válidos, coluna ID, sem duplicatas ou IDs inválidos. Para a tela de contatos, 1.427 usernames com formato válido e 7.162 linhas sem username válido; existência desses perfis ainda não validada no Telegram. Dados pessoais não foram adicionados ao repositório.
- 15 testes passaram em SQLite e PostgreSQL 16 real. Auditoria cobre importação, IDs grandes, ambiguidade, comparação, login/2FA, autenticação, FloodWait, persistência e exportação. Contatos cobre importação repetível, exclusão de linhas sem username, envio único e prevenção de duplicatas, cooldown, confirmação, bloqueio, ID divergente, imagem/caption, privacidade e resultado incerto após perda de conexão.
- Teste de navegador Chromium com Next e FastAPI reais, usando Telethon simulado: login/código/2FA, importação CSV, busca, seleção, personalização `{nome}`, prévia PNG, confirmação, um envio simulado, próximo contato, bloqueio, proteção de origem e viewport mobile passaram. O teste verificou que o outro contato permaneceu pendente e que não houve erros JavaScript.
- Next.js 16.4.0: build de produção e TypeScript passaram. Proxy mantém APP_TOKEN no servidor e não exige token de bot no dashboard. A auditoria continua em `/auditoria`.
- Os processos de teste não se conectaram ao Telegram real. O servidor fictício está em backend/tests/browser_server.py e não participa do startup normal.
- A execução desta versão foi feita em Linux. O usuário já conseguiu instalar as dependências Python/frontend e iniciar PostgreSQL no Windows; o login e envio da nova versão no Windows ainda estão pendentes.

Não houve autenticação real, resolução real de usernames, leitura real de diálogos ou envio de mensagens. Essas operações dependem de API ID/API Hash e da conta do usuário. A disponibilidade de usernames, permissões e limites de envio é determinada pelo Telegram. Enviar lentamente não elimina risco de limitações ou suspensão.

Há um aviso de depreciação da integração Starlette/AnyIO nos testes, sem falhas. O download de um Chromium adicional foi bloqueado pela política de rede; o teste de navegador foi concluído usando /usr/bin/chromium já instalado, sem alterar a política nem desabilitar TLS.


## Exclusão de contatos

- 20 testes Python passaram em SQLite e PostgreSQL real: 15 anteriores, 2 do filtro de planilha e 3 de exclusão. Cobrem confirmação, persistência, bloqueio de envio/reimportação, username alterado com ID conhecido, preservação de histórico, autenticação e operação em andamento.
- Build de produção passou após adicionar o botão e a rota de exclusão.
- O updater Windows baixa quatro arquivos da revisão exata, compara checksums e faz backup. Não foi executado em Windows neste ambiente Linux. Ele não altera sessões, configurações, dependências ou banco.
- A preparação de hospedagem que o usuário cancelou foi preservada em arquivo local fora do checkout; esta atualização publica apenas o sistema local e a exclusão.
- Teste Chromium passou: cancelar/confirmar exclusão, atualização dos contadores, manutenção de exclusões após nova importação, seleção do próximo e remoção do último contato sem erro. Nenhum contato real foi excluído durante testes.

- Correção do updater após execução no Windows: Invoke-WebRequest interpretava `[...path]` no caminho de saída. Downloads e backups agora usam nomes planos derivados de SHA256; a instalação/restauração usa System.IO.File.Copy com caminhos literais. Os quatro downloads reais da revisão publicada foram conferidos com seus checksums. Não foi possível instalar PowerShell nesta máquina de teste (imagem Microsoft e API de release bloqueadas por HTTP403); a execução completa do helper corrigido no Windows permanece pendente.

## Formatação de mensagens

- 23 testes Python passaram: os 20 anteriores e 3 de formatação. A suíte foi executada em SQLite e PostgreSQL 16. Cobre modo literal por padrão, HTML opcional em texto/legenda, entidades de negrito com emoji pelo parser real do Telethon, limites pelo texto visível e rejeição de marcações inválidas antes de resolver o destinatário ou enviar.
- Build de produção e TypeScript passaram. Teste Chromium passou com o botão Negrito, substituição de `{nome}`, prévia formatada e envio simulado com imagem, mantendo as verificações de login, importação, exclusão e mobile.
- A prévia usa elementos React de uma lista restrita, sem inserir HTML arbitrário. Nomes são escapados no modo HTML. O modo antigo continua literal, com `parse_mode=None`; o modo opcional usa `parse_mode='html'` tanto em texto quanto em legenda.
- `atualizar-formatacao.ps1` usa o mesmo procedimento de download verificado, backup e restauração do helper de exclusão. Não exige novas dependências nem altera configuração, sessão ou banco. Sua execução completa em Windows não foi verificada neste ambiente Linux.
- Nenhuma mensagem real foi enviada, editada ou reenviada durante estes testes. A atualização vale para os próximos envios feitos com a opção de formatação ativada.
