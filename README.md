# RoboMario

Aplicação local (intranet) para processar planilhas padrão de anomalias e preparar os dados para criação de Ordens de Trabalho no BMA.

A criação automática de OT (SharePoint + Selenium) **não está implementada nesta etapa**. Existe apenas o contrato `BMAService.criar_ot(dados_json)`.

## Stack

- Frontend: Next.js 15, TypeScript, Tailwind CSS
- Backend: Python FastAPI, Pandas, OpenPyXL
- Banco: SQLite (`database/data/bma_intranet.db`)

## Estrutura

```text
bma-intranet/
├── frontend/
│   ├── components/
│   ├── pages/
│   └── services/
├── backend/
│   ├── api/
│   ├── services/      # inclui BMAService.py
│   ├── models/
│   └── utils/
└── database/
    └── data/
```

## Regras de negócio

1. Aceita somente `.xlsx` e `.xls`.
2. A planilha deve conter a coluna obrigatória **Nº OT BMA**. As demais colunas são identificadas automaticamente.
3. Se a estrutura for inválida, o sistema bloqueia o processamento e exibe:
   `Arquivo inválido. Utilize o modelo padrão de importação.`
4. Uma linha só é elegível se **Nº OT BMA** estiver vazio **e** o **TaskStatus** não for Planejado, Concluído, Preparado ou Cancelado. OT preenchida ou um desses status tornam a linha inelegível.
5. Cada linha elegível vira um objeto JSON (chaves geradas a partir dos nomes das colunas).
6. O histórico fica na tabela `arquivos_processados`.
7. Logs registram arquivo carregado, data/hora, quantidade processada e erros.

## Pré-requisitos

- Python 3.11+ (testado com 3.13)
- Node.js 18+ (testado com 24)
- npm

## Execução local

Abra **dois terminais**.

### Continuar em outro computador

Use somente um repositório privado aprovado para este projeto. Clone o repositório e abra a pasta no VS Code. Instale Python, Node.js e Firefox; depois execute os passos de backend/frontend abaixo, ajustando o caminho para a pasta clonada.

O repositório não transporta banco SQLite, OTs reais, equipe, planos/revisões salvos, uploads, credenciais nem perfil autenticado do Firefox. O banco vazio é criado ao iniciar a API; os dados precisam ser coletados novamente com acesso autorizado à rede/BMA/SharePoint. Para transferir dados operacionais, use o meio corporativo aprovado, fora do Git. No outro computador, o login/MFA deve ser feito novamente.

Antes de trocar de computador, confira se o commit local também foi enviado ao remoto; um commit sem `push` não estará disponível em casa. Dependências (`.venv`, `node_modules`) e build (`.next`) são reinstalados localmente, não versionados.

### 1. Backend (porta 8000)

```powershell
cd C:\Users\e062942\bma-intranet\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

API: http://localhost:8000  
Documentação: http://localhost:8000/docs

### Integração Selenium com o BMA

O endpoint de planejamento abre o Firefox em segundo plano no **Relatório rápido** e aciona automaticamente o botão principal de login. O perfil fica em `%LOCALAPPDATA%\BMA_Automacao\FirefoxProfile` para reutilizar a sessão autorizada. Se o BMA exigir autenticação interativa ou MFA, a coleta será interrompida com um erro; senha e MFA não são lidos nem armazenados pelo aplicativo, e a autenticação não é contornada.

Instale as dependências no ambiente do backend e inicie-o:

```powershell
cd C:\Users\e062942\bma-intranet
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\backend\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --reload --port 8000
```

O Selenium Manager inicia o GeckoDriver. Se o Firefox não estiver no local padrão, configure `BMA_FIREFOX_BINARY` com o caminho de `firefox.exe`; `BMA_LOGIN_TIMEOUT` altera o tempo de espera pelo login/MFA.

Ao sincronizar, o coletor consulta todas as páginas OSLC de `mxwo` pelo contexto autenticado do Firefox. Os setores são enviados com `maintenanceshop in [...]`; os status `CAN`, `CLOSE`, `COMP` e `HISTEDIT` são excluídos. A validação local mantém OTs de RES, não históricas e que não sejam tarefas. O payload retornado é preservado em JSON no SQLite.

A seleção explícita inclui instruções completas, equipamento/local, plano de trabalho (`jpnum`), PM (`pmnum`), rota, equipe, duração, horas de mão de obra e datas de acompanhamento. Inclui também `sneconstraint` (não iniciar antes), `fnlconstraint` (não terminar depois), `pmduedate` e `pmnextduedate`. Não usa `oslc.select=*`.

**Atualizar banco de dados · OTs do BMA** fica sempre disponível na tela inicial de planejamento, mesmo após uma coleta concluída, separado de **Continuar planejamento**. Reutiliza a sincronização existente e seus logs, impedindo disparo enquanto há atualização ativa. A consulta passa a solicitar `wplabor{wplaborid,craft,orgid,quantity,laborhrs,skilllevel}` para trazer a especialidade do serviço (não a do funcionário), quantidade, horas normais e nível. As linhas completas são preservadas em `ordens_trabalho.dados_json`, expostas em `dados.wplabor`, inclusive para tarefas/filhas. Links de continuação da coleção são consultados com validação de origem; resposta inválida interrompe a coleta antes de gravar. Sem linhas, não se inventa especialidade. O contrato deve ser validado na instância Michelin após login/MFA; se o BMA rejeitar a relação/campos, a sincronização informa erro e não deve ser considerada concluída. Esta coleta não altera o cadastro de funcionários.

Para OTs com `haschildren`, consultas paginadas em lotes de até 40 pais coletam as filhas e tarefas **diretas**, inclusive encerradas ou de outro setor, vinculadas pelo pai e site RES. Elas são salvas em `dados.children`, sem aumentar a contagem da carteira principal. Falhas nessa etapa interrompem a sincronização antes da gravação. Não há expansão recursiva de descendentes nem consulta de materiais, ferramentas ou anexos.

Na tabela de planejamento, **Ver** abre as instruções, dados de preparação, datas e filhas/tarefas, cada uma com seus detalhes. Datas são exibidas em `America/Sao_Paulo`, mantendo os valores originais com fuso no JSON; vencimentos de PM também mostram o horário convertido, sem usá-lo como regra automática de programação. Registros antigos precisam de nova sincronização para receber os novos campos.

### Cadastro de mão de obra e especialidades

A atualização de mão de obra é iniciada **somente pelo botão Atualizar mão de obra dentro do modal**. Sincronizar OTs não altera o cadastro de funcionários. O coletor consulta todas as páginas de `mxlabor` com `worksite="RES" and status="ACTIVE"`, trazendo matrícula, nome, organização, setor, local e especialidades. **Status ACTIVE do BMA não comprova vínculo empregatício nem disponibilidade por data/turno.**

O snapshot de profissionais é armazenado em `mao_de_obra`. Para NF, a mesma atualização consulta a lista corporativa `NF-RES/ListaFuncionario` via REST na sessão local autenticada do Firefox. Toda pessoa presente nessa lista é considerada ativa, conforme regra operacional definida pelo usuário (a coluna Status não é usada). Se BMA ou SharePoint falhar, a atualização informa erro e preserva os snapshots anteriores. O novo cadastro BMA e a lista NF são gravados na mesma transação. `mao_de_obra_sync` registra data e quantidade.

O efetivo NF é a interseção entre **todo o cadastro RES/ACTIVE do BMA, sem filtro de setor de manutenção ou local**, e as pessoas vinculadas à ListaFuncionario do SharePoint NF. Matrícula e função vêm do BMA. Sem conferência inicial, não há efetivo NF liberado. Matrícula exata ou nome completo idêntico (normalizados por acentos/caixa) e únicos permitem vínculo automático; nomes abreviados não são associados por aproximação. A lista atual possui a coluna `Matr_x00ed_cula`, mas os registros inspecionados estavam sem matrícula. A seção **Conferência de ativos NF**, dentro do modal, permite confirmar e corrigir vínculos persistidos por ID SharePoint + organização/matrícula BMA, oferecendo todos os candidatos RES. Pessoas sem vínculo ou ambíguas não entram no efetivo; seus nomes são exibidos para conferência. Nenhum dado é escrito no SharePoint ou no BMA. Em seleção mista, soma-se o efetivo elegível dos demais setores, sem duplicar pessoas.

O catálogo fixo está em `database/catalogos/especialidades.json`, extraído da planilha fornecida pelo usuário; a cópia original fica em `database/catalogos/especialidades.xlsx`. São 273 registros de cinco organizações, dos quais 54 de BR. Na inicialização, o catálogo é carregado na tabela `especialidades`, usando a chave **organização + código**, pois um código pode ter descrições diferentes entre organizações. Códigos desconhecidos não recebem descrições presumidas. O catálogo independe da sincronização do BMA e não precisa mais do arquivo na pasta Downloads.

Ao lado do menu de planejamento, preencha **Início do planejamento** e **Fim do planejamento** (inclusive) para habilitar **Definir Mão de Obra**. O botão abre um modal com o cadastro local e a última atualização. As listas **Efetivo total** e **Disponível** permitem seleção múltipla e transferência por `>`/`<`; `>>` adiciona todos os resultados da busca e `<<` remove todos. Cada executante é contado uma única vez, em uma das suas funções cadastradas. A função principal é sugerida, mas pode ser alterada.

**Planejar PM** e **Planejar Corretiva**, incluindo a tabela de planejamento, só são liberados após salvar ao menos um executante disponível para o período e conjunto de setores atuais. Apenas abrir o modal ou salvar uma equipe vazia não libera o planejamento. Alterar o período bloqueia novamente os botões até revisar e salvar a equipe; uma equipe previamente salva para o mesmo período/setores é restaurada e libera os botões ao reabrir.

Para **NF**, o efetivo mostrado no modal é RES do BMA cruzado com a ListaFuncionario do SharePoint, independentemente do setor/local BMA. Para os demais setores, permanece a seleção por setor de manutenção ou local exatamente `NFE`. A API filtra o retorno e o backend revalida a elegibilidade ao salvar. Seleções antigas fora do escopo aparecem como pendentes para conferência e não entram no H×H.

**Regra atual de capacidade: dias disponíveis marcados × 8 horas por executante**, para todos, independentemente da jornada, equipe, turno, folga ou marcação especial do calendário. Segunda a sexta vêm marcados inicialmente. É possível incluir sábados, domingos e feriados, retirar qualquer dia ou marcar/retirar intervalos. Os dias verdes representam disponibilidade; desmarcados valem zero. O H×H individual, por função e do painel é atualizado automaticamente, sem campo manual de horas ou ajuste geral. Feriados não são retirados automaticamente.

O calendário oficial de quatro equipes está preservado em `database/catalogos/turnos-2026.pdf` e `turnos-2026.json`. A equipe/jornada é **informativa** na nova regra. **Ver turnos (informativo)** exibe A = 00h–08h, B = 08h–16h, C = 16h–00h, F = folga e marcações especiais de 2026, mas não exige horas manuais. Fora de 2026, a referência não é extrapolada; a capacidade por dias marcados continua funcionando.

**Compatibilidade:** planos antigos (`escala` ou `dias_6h`) mantêm seus cálculos salvos até revisão. Ao abrir no modal, o rascunho passa a `capacidade="dias_8h"`; preserva os dias explicitamente escolhidos no mesmo período ou inicia segunda a sexta menos as ausências antigas. Ajustes e horas especiais não são transferidos: o novo total é exatamente dias × 8. Cancelar não modifica o plano salvo. Salve para aplicar 8 h/dia ao painel. O backend rejeita dias duplicados, inválidos ou fora do período e não aceita ajustes/ausências paralelos na nova regra.

O modal mostra o H×H individual e o somatório por função. Configurações incompletas ou pessoas que deixaram de constar no cadastro ativo não são incluídas no total, são sinalizadas como pendentes e impedem salvar. O backend revalida a função e o cadastro ativo ao salvar, sem confiar nos totais do navegador. **Salvar período e equipe** persiste o último planejamento de cada conjunto de setores na tabela `planejamento_equipes`, compartilhado nesta instalação, e o restaura ao reabrir. Cancelar descarta as alterações do modal. Alterar o período exige abrir o modal e salvar novamente para persistir o novo período e recalcular a capacidade. Ainda não há atribuição dos executantes a OTs individuais nem leitura automática dos calendários do BMA.

### Histórico, padrão pessoal e dias disponíveis

- **Planejador:** nome/matrícula declarado no modal, obrigatório ao salvar, lembrado neste navegador. Não equivale a autenticação ou controle de acesso.
- **Histórico:** cada salvamento registra período, equipe, dias disponíveis e planejador (ou o formato legado em planos anteriores). São retidas somente as últimas **10 versões por conjunto normalizado de setores**, compartilhadas, em `planejamento_historico`.
- **Meu padrão:** uma equipe por planejador + conjunto de setores, preservando função, jornada e equipe, sem datas. Ao aplicar o padrão, segunda a sexta vêm marcados no período atual. Aplicar histórico no mesmo período preserva os dias disponíveis; para outro período, reinicia segunda a sexta. Tudo é aplicado como rascunho e exige revisão/salvamento.
- **Disponibilidade:** combo por executante para segunda a sexta, todos os dias ou nenhum dia; seleção personalizada diretamente nos dias. É possível marcar/retirar intervalos e copiar os dias disponíveis para os executantes selecionados na caixa Disponível.
- **Datas:** campos visíveis de planejamento e intervalos usam sempre `dd/mm/aaaa`, com máscara, validação e atalho de calendário, independentemente do idioma do navegador. A API continua usando ISO `aaaa-mm-dd`.
- Atualização e vínculos persistem mesmo se depois cancelar o rascunho da equipe; o botão informa progresso/erro, impede operações concorrentes e não sincroniza OTs.

### 2. Frontend (porta 3000)

### Centro de Planejamento PCM

`/planejamento/ots` reúne diagnóstico executivo, configuração do período/equipe e carteiras PM/corretiva. O frontend usa Lucide, Framer Motion (respeitando redução de movimento) e Recharts. O modo TV amplia o espaço de trabalho em telas grandes. **Recarregar dados** lê o SQLite, não inicia nova coleta no BMA.

- **Indicadores e carteira:** para a preventiva, entram OTs abertas cujo início-alvo (`targstartdate`), término-alvo (`targcompdate`), início programado (`schedstart`) ou término programado (`schedfinish`) esteja no período, ou cujo intervalo alvo ou programado cruze o horizonte. Comparação inclusiva em datas de Brasília; datas civis não mudam por fuso. **A preventiva exige tipo I/S e descrição começando com `PM` (ignorando espaços iniciais e caixa): PM1 Segurança, PM2 Qualidade e PM3 Manutenção. A corretiva tipo E é uma carteira aberta, sem filtro de data-alvo/programada e sem exigir prefixo PM.** Status terminais continuam excluídos. Os indicadores do horizonte combinam a seleção por data com toda a corretiva aberta. Datas e equipe válidas continuam obrigatórias para alocar; estimativas ausentes impedem calcular backlog completo. Assertividade depende de histórico e permanece indisponível.
- **Carteiras:** preventivas I/S e corretivas E, com contagens, HH estimado e equipamentos distintos. Criticidade, risco e valor estimado não são inferidos de outros campos. O bloqueio por período/equipe continua obrigatório; o cadastro ativo e a função são revalidados ao carregar o painel.
- **Temporal:** calendário/heatmap paginado em 28 dias, carga diária e Gantt de até 12 OTs por intervalo, somente das OTs selecionadas para o horizonte. O Gantt usa apenas `schedstart`/`schedfinish` válidos; datas-alvo não representam programação confirmada. O HH integral é contabilizado na data de início programada quando ela cai no período, sem distribuir artificialmente serviços cuja data de início esteja fora do horizonte. Na nova regra, a capacidade diária soma 8 h por executante disponível naquele dia. Planos legados mantêm seus cálculos até revisão.
- **Equipe:** nome, especialidade, escala, dias e HH disponíveis. HH comprometido e saldo por dia são consultados na bancada integrada, a partir dos vínculos executante × OT persistidos.
- **Insights da IA:** regras locais de qualidade, concentração de OTs por local e pressão diária de HH, sem modelo de IA conectado nem envio de dados externos. Não representam previsão validada ou diagnóstico de criticidade.
- **Fluxo de oito etapas:** período e equipe configuráveis, recursos/materiais com limites de integração informados, ordens consultáveis e simulação de capacidade agregada (sem modificar dados). Alocação e confirmação local ficam na bancada; aprovação corporativa e publicação continuam não implementadas. A barra não marca etapas futuras como concluídas. O resumo executivo pode ser exportado em CSV; carteiras são exportadas em Excel real.

### Bancada integrada, confirmação e acompanhamento

- Os cards PM e corretiva oferecem **Exportar Excel filtrado** (`.xlsx` real). Aplicam os filtros atuais das colunas da tabela à respectiva carteira. A API revalida o conjunto de OTs; datas têm formato Excel `DD/MM/YYYY`, e textos são gravados como texto literal, nunca como fórmulas.
- **Atualizar BMA e gerar Excel NFE**, no Centro PCM e na bancada, inicia uma nova coleta exclusiva de `RES-TC-NF` (login/MFA no Firefox quando solicitado). Somente após sucesso baixa **Planejamento NFE.xlsx**, aba **Report**. Exporta todas as OTs abertas retornadas nessa coleta, sem filtros da tabela, tipo ou período; mantém as exclusões de status da coleta normal. A API exige o identificador da coleta concluída e verifica a quantidade e a janela de atualização, sem incluir registros antigos retidos no banco nem baixar dados anteriores em caso de falha. O plano aberto não é modificado. O formato replica as 29 colunas físicas A:AC do modelo fornecido, título na linha 2, cabeçalhos na linha 3, mesclagens e pares separados de data/hora. `Refere-se a` corresponde a `origin` (conferido em 27 OTs do BMA); `Grupo de Preparadores` corresponde a `planner` (428 correspondências entre modelo e banco). Datas usam o fuso de Brasília; horas estimadas/duração usam `[h]:mm` para não reiniciar após 24 h. A descrição longa é exportada sem marcação HTML, e textos nunca são fórmulas.
- **Planejar PM / Planejar Corretiva** abre `/planejamento/alocacao`. Um único plano por conjunto de setores e horizonte é reutilizado; as duas carteiras compartilham a mesma capacidade. A equipe deve ter sido salva com `dias_8h` e planejador identificado.
- A criação congela equipe, dias e carteira do snapshot local. Alterar o modal depois não modifica silenciosamente um plano existente. Indisponibilidades durante a execução são registradas na bancada; novos períodos geram planos separados. O snapshot não representa consulta em tempo real ao BMA.
- Prepare cada OT com **duração por pessoa**, **quantidade de pessoas**, **organização/especialidade** e prioridade (1 primeiro). Somente `estdur` válido é sugerido como duração inicial. Com uma única linha BMA de mão de obra planejada, especialidade/organização e quantidade inteira válida são preenchidas; se faltar organização, só é resolvida quando há uma única organização compatível na equipe. Múltiplas especialidades ficam visíveis, sem reduzir equipes distintas a uma única função automaticamente. `laborhrs` não é tratado como duração por pessoa. Duração de 4 h com 2 pessoas equivale a 8 HH. Requisitos são locais e não alteram as estimativas originais do BMA. A bancada não exige mais checkbox de conferência de recursos; o campo legado `liberada` é preservado, mas não condiciona alocação, sugestão ou confirmação.
- Em **Especialidade exigida**, **Todos — qualquer especialidade da equipe** permite equipes mistas na sugestão, ao arrastar e na edição manual. É uma escolha explícita, persistida como `todas_especialidades=true`; não significa selecionar todos os integrantes. Mantém quantidade simultânea, dias disponíveis, capacidade e conflitos. Ao escolher uma especialidade específica novamente, a restrição por organização/função volta a valer. A conferência das habilitações reais continua sendo responsabilidade do planejador.
- **Galeria e filtros:** galeria vertical com rolagem própria e botões anterior/próximo à esquerda; cronograma ao lado no desktop. No celular as áreas são empilhadas. Menu **Filtros** recolhível com busca, PM1/PM2/PM3 (prefixo da descrição), outras PM/corretivas e especialidade exigida. Especialidades vêm de `dados.wplabor` (inclusive múltiplas); na ausência, usa a preparação manual, nunca infere função pela descrição. **Selecionar todas as filtradas** marca o conjunto inteiro, inclusive cartões ainda não renderizados. Marcas de outros filtros permanecem salvas, mas lote e sugestão usam somente as marcadas nos filtros atuais. OTs completas/posicionadas saem da galeria, sem apagar snapshot/seleção; parciais continuam com saldo pendente.
- **Arraste pelos seis pontinhos:** segure o ícone e solte no nome ou célula executante/dia. Uma OT marcada leva o lote marcado dos filtros atuais; uma não marcada leva somente ela. Pointer Events dão suporte a mouse/toque e rolagem automática nas bordas da tela e da grade. O destino fica destacado; o formulário continua disponível. Pendências de preparação/capacidade são explícitas, sem horas fictícias.
- Soltar no **nome do executante** distribui pelos dias disponíveis a partir do início do plano e apresenta as atividades nos quadrados correspondentes; soltar diretamente em um quadrado começa naquele dia. Nome e célula recebem destaque durante o arraste. Após alocar, a tela leva ao dia preenchido. Se faltarem duração, quantidade de pessoas ou especialidade, informa exatamente os campos pendentes e leva à preparação; não presume dados nem esconde a OT sem alocação.
- **Quadrado exato:** soltar em uma célula fixa o cartão naquele executante/dia, sem exigir outro clique para ele aparecer. Com requisitos completos, usa primeiro o saldo diário de referência dos integrantes (8 h menos a carga existente), continuando nos próximos dias da mesma semana. Exemplo: 6,4 h já ocupadas na segunda e atividade nova de 8 h geram 1,6 h na segunda e 6,4 h na terça. Não ultrapassa automaticamente a referência diária nesse arraste; sobrecarga diária intencional continua possível pela edição de bloco, respeitando a capacidade semanal. Se faltarem dados/equipe/capacidade, mantém um **cartão posicionado no rascunho**, em `posicionamentos`; ele sai da carteira, pode ser movido ou devolvido à carteira. O posicionamento é salvo na revisão/PDF sem inventar duração ou reserva de horas. Complete pelo editor e clique **Adicionar bloco**; a confirmação exige resolver ou retirar as pendências. Planos antigos continuam compatíveis.
- **Editor opcional pela canetinha:** fica recolhido até clicar no lápis junto aos seis pontinhos da carteira (ou em um cartão já posicionado/alocado). Arrastar não abre o editor. Duração e especialidade continuam partindo dos dados BMA do snapshot, com alterações manuais preservadas. A quantidade BMA orienta a pré-seleção dos integrantes; **Pessoas simultâneas** é uma saída calculada, não um campo digitável. A inclusão grava a quantidade efetivamente selecionada e exige consistência com os blocos anteriores da OT. Para novos blocos, os dias do horizonte são checkboxes; verde identifica as datas-alvo/programadas BMA dentro do período, não as restrições de início/fim. **Adicionar bloco** distribui a duração restante somente entre os dias marcados, usando a disponibilidade comum dos executantes, e fecha o editor. Se os dias não comportarem a atividade ou cruzarem semanas, informa erro sem incluir blocos parciais. Editar um bloco existente mantém controles de dia/horas e valida a quantidade de integrantes.
- **Grade compacta:** cartões mostram apenas número da OT, PM/corretiva e descrição. Horas/equipe e pendências ficam no editor ou na dica ao passar o mouse; o ícone de retorno à carteira aparece ao passar o mouse, focar o cartão ou usar tela de toque. Cada célula tem barra e percentual de carga diária, horas ocupadas e horas disponíveis, com referência de 8 h nos dias disponíveis (zero nos indisponíveis). Cartões pendentes não reservam horas. Acima de 8 h, o percentual pode superar 100%, a barra fica cheia e âmbar; só excesso semanal recebe alerta vermelho. A visualização não cria um limite diário novo.
- **Planos existentes:** depois da coleta BMA, clique **Reler especialidades do banco** na bancada. A API relê apenas a mão de obra planejada das OTs do snapshot; não substitui carteira, disponibilidade ou alocações. Completa requisitos ausentes somente em OTs não alocadas, sem sobrescrever escolhas manuais. A atualização fica na tela até **Salvar**; nova revisão persiste os dados, mantendo PDFs anteriores imutáveis. Se não houver coleta no banco, informa erro. O botão **Atualizar banco pelo BMA** leva à tela inicial.
- **Planejamento por dia, sem hora de início:** cada alocação informa o dia e as horas da atividade. A referência diária é 8 h, mas é permitido planejar mais de 8 h em um dia se a soma do executante na semana couber na capacidade dele. **Capacidade semanal = dias disponíveis naquela semana × 8 h**, descontando indisponibilidades. A semana vai de segunda a domingo; não se compensa excesso de uma semana com saldo de outra, nem saldo de outra pessoa. A grade mostra saldos por semana, não conflitos de horário. O campo técnico legado `inicio` é mantido por compatibilidade, ignorado na programação e normalizado para zero em novas revisões; PDFs/snapshots antigos permanecem imutáveis.
- **Distribuir lote:** arraste a área do lote ou uma OT marcada até o **nome do executante**, ou use **Distribuir sem arrastar**. Somente marcações dos filtros atuais são incluídas. Distribui a duração restante pelos dias da mesma semana, até a capacidade semanal individual. Preserva alocações existentes, especialidade, quantidade de pessoas, ausências e restrições de data. Lotes soltos numa célula usam o saldo diário e continuam nos dias seguintes; não exigem que cada OT comece no mesmo quadrado. Se 12 h forem atribuídas com apenas 10 h livres na semana, aloca 10 h e informa 2 h pendentes, bloqueando a confirmação da atividade parcial.
- **Reordenar no cronograma:** arraste um cartão alocado sobre outro para inserir a OT antes dele (linha de inserção destacada). Move a atividade inteira, inclusive continuações. Reprograma as OTs já alocadas dos executantes de origem/destino na mesma semana, usando espaço diário comum das equipes e restrições BMA. Soltar numa célula vazia define o dia mínimo da atividade movida; trocar integrante substitui somente o membro de origem. Duração já alocada e equipe dos demais trabalhos são preservadas. OTs com equipes variáveis entre blocos exigem ajuste no editor antes de reordenar. Se a nova sequência não couber, nenhuma alteração é aplicada. Ordem e dias são persistidos na revisão/PDF, sem ordenação alfabética automática.
- Alocações podem ser divididas entre dias, movidas e editadas, sem definir sequência/horário. A quantidade exigida de pessoas participa de cada alocação diária; a ferramenta não comprova simultaneidade de horários nem valida habilitações especiais, segurança/liberação operacional, materiais ou ferramentas automaticamente. Para mudar a atividade para outra semana, retire e reprograme a OT integralmente.
- **Sobrecarga semanal na prévia:** edições manuais/arrastar podem gerar excesso semanal para revisão. Alocações dos integrantes com semana excedida ficam vermelhas; carga diária acima de 8 h, sozinha, não é erro. O rascunho pode ser salvo, mas a confirmação e revisões de planos já confirmados exigem capacidade semanal válida. O PDF identifica excesso semanal, não choque de horário.
- **Sugerir encaixe** considera somente OTs marcadas da etapa PM/corretiva, por prioridade, data-alvo e OT, distribuindo horas por dia até a referência de 8 h e respeitando o saldo semanal. Preserva todos os blocos existentes. Pode ficar parcial por falta de capacidade; exige revisão e salvamento. Corretivas usam o saldo deixado pelas PMs.
- O backend valida capacidade semanal na confirmação/revisões operacionais; disponibilidade, especialidade, quantidade de pessoas, duração total e datas `sneconstraint`/`fnlconstraint` continuam obrigatórias mesmo no rascunho (granularidade diária). Não transforma data-alvo em restrição rígida para corretiva. OTs marcadas precisam estar integralmente alocadas para confirmar; para postergar uma OT marcada, retire seus blocos e desmarque-a explicitamente.
- **Revisar e confirmar** apresenta a grade PM + corretiva e as atividades não alocadas/parciais em conjunto. É possível preparar/encaixar ou retirar OTs. Atividades parciais não podem ser confirmadas; complete ou retire. A confirmação inicial exige ao menos uma alocação e é **local, não aprovação corporativa autenticada**. Cadastro ativo e status das OTs são revalidados; planos confirmados com horizontes sobrepostos não podem duplicar OTs. A carga semanal da pessoa é somada entre planos confirmados, contando cada dia disponível apenas uma vez e descontando ausências registradas; não se verifica sobreposição por horário.
- **Acompanhar planejamentos**, na primeira tela de planejamento, abre `/planejamento/acompanhamento`: pesquisa por setor, planejador, período e status. Reabre o mesmo cronograma durante a execução para mover ou retirar atividades. A bancada não oferece mais formulário de faltas ou edição de observações; indisponibilidades e observações legadas permanecem nos snapshots e PDFs. Pode-se confirmar uma revisão sem atividades remanescentes quando todas foram postergadas e desmarcadas. Não há transferência automática para outra semana: prepare um novo horizonte, conferindo a carteira e as pendências anteriores.
- A bancada foi simplificada: não exibe mensagem de Todos, conferência de recursos, campo de restrições/postergação, formulário de faltas, motivo da revisão ou lista de PDFs. Observações/indisponibilidades já registradas são preservadas e consideradas; não são apagadas ao salvar. Todo salvamento registra automaticamente **Atualização do planejamento** e cria revisão imutável (`pcm_planos`, `pcm_revisoes`) com snapshot e **PDF binário arquivado no próprio SQLite do projeto**. A API mantém histórico e PDFs antigos, e o botão do PDF da revisão salva permanece no cabeçalho. Controle otimista de revisão rejeita sobrescrita concorrente (HTTP 409). Alterações na tela não estão persistidas até salvar.
- **PDF executivo:** novas revisões usam A4 retrato, cabeçalho azul/amarelo com a marca recortada da imagem fornecida pelo usuário (`backend/assets/michelin-header.png`), título fixo **PLANEJAMENTO SEMANAL NFE** e período dinâmico em `dd/mm/aaaa`, KPIs reais (OTs distintas com alocação, HH, recursos, locais e ocupação), cronograma agrupado por dia, sem faixa/horário de início, com equipe, OT/tipo, local, descrição, horas/HH e situação de alocação. Excesso semanal fica sinalizado em vermelho; carga diária acima de 8 h não é tratada isoladamente como erro. Cabeçalhos e datas de agrupamento se repetem nas continuações; textos extensos não são truncados. O resumo inclui barras de carga e rosca de cobertura (programadas integralmente, parciais e não alocadas), sem inventar criticidade ou execução. Para horizontes longos, barras são agregadas em até sete grupos de dias com carga e identificadas como tal; o cronograma mantém os dias exatos. Pendências/indisponibilidades ficam em anexo. O número de páginas cresce conforme o conteúdo, sem comprimir todo o plano em uma página ilegível. Revisões anteriores mantêm seus PDFs originais; para adotar o novo layout, salve uma nova revisão.
- **BMA e SharePoint aguardam configuração**, conforme decisão do usuário. O botão de envio ao BMA está desabilitado; não há publicação fictícia nem upload. PDF pode ser baixado. A pasta SharePoint de destino e o contrato de gravação BMA deverão ser definidos e testados em homologação antes de habilitar integrações.
- O PDF usa ícones vetoriais de ordens, relógio, pessoas, localização e carga, com valores e legendas na mesma grade horizontal. Metadados têm rótulos fixos; OT, horas/HH e situação ficam centralizados, enquanto recurso, local e descrição ficam à esquerda. Células usam alinhamento vertical central e espaçamento uniforme. Dias têm faixas laterais alternadas em azul/amarelo e rodapé próprio de total HH; grupos que cabem na página são mantidos juntos. Textos longos continuam pagináveis, sem truncamento. O resumo também usa ícones e gráficos vetoriais.

Testes desta bancada (bancos temporários, sem alterar equipe real):

```powershell
$env:PYTHONPATH = "$PWD\backend"
.\backend\.venv\Scripts\python.exe -m unittest backend.tests.test_pcm_planning
cd frontend
node --test tests\pcmDashboard.test.cjs tests\laborPlanning.test.cjs tests\workPlanning.test.cjs
npx tsc --noEmit
```

O teste opcional `backend.tests.test_pcm_browser` usa Selenium/Firefox com os serviços em 3000/8000 (`PCM_E2E=1` e `PYTHONPATH=backend`). Ele cria somente registros com setor/identidades UUID de teste, confere Excel, arrastar, sugestão, confirmação, PDF, falta, edição manual e responsividade e remove esses registros no encerramento, sem sincronizar BMA ou SharePoint.

O calendário civil de Itatiaia enviado separadamente ainda não altera os cálculos; a política de feriados permanece a já documentada.

```powershell
cd C:\Users\e062942\bma-intranet\frontend
npm install
npm run dev
```

Se o `npm install` falhar com `SELF_SIGNED_CERT_IN_CHAIN` (proxy corporativo), execute:

```powershell
$env:NODE_TLS_REJECT_UNAUTHORIZED = "0"
npm install --strict-ssl false
```

Planilha de exemplo para teste: `database/data/modelo_anomalias.xlsx`.

Interface: http://localhost:3000

O frontend chama o backend em `http://localhost:8000`. Para alterar, use `NEXT_PUBLIC_API_URL`.

## Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/health` | Status do sistema |
| POST | `/api/processar` | Upload e processamento da planilha |
| GET | `/api/dashboard` | Último arquivo, totais e status |
| GET | `/api/historico` | Últimos arquivos processados |
| GET | `/api/logs` | Logs persistidos |
| POST | `/api/planejamento/sincronizar` | Busca e grava OTs OSLC do setor selecionado |
| GET | `/api/planejamento/ots?setor=RES-TC-NF` | Lista OTs gravadas; aceita `status` repetido para filtrar |
| GET | `/api/planejamento/mao-de-obra?setor=RES-TC-NF` | Profissionais ativos dos setores informados ou do local NFE (parâmetro de setor obrigatório e repetível) e data da coleta |
| GET | `/api/planejamento/especialidades?orgid=BR` | Catálogo fixo de especialidades por organização |
| GET | `/api/planejamento/equipe?setor=RES-TC-NF` | Último período e equipe salvos para o conjunto de setores |
| PUT | `/api/planejamento/equipe` | Valida jornada/função, calcula H×H e salva período/equipe |
| GET | `/api/planejamento/calendario-turnos` | Calendário oficial das quatro equipes de 2026, com horários e marcações especiais |
| POST | `/api/planejamento/mao-de-obra/atualizar` | Inicia atualização BMA/SharePoint; progresso pela API de sincronização |
| GET/PUT | `/api/planejamento/vinculos-nf` | Confere e confirma vínculos entre pessoas SharePoint e BMA |
| GET | `/api/planejamento/historico` | Últimas 10 versões da equipe por conjunto de setores |
| GET/PUT | `/api/planejamento/equipe-padrao` | Equipe padrão por planejador e conjunto de setores |
| GET/POST | `/api/pcm/planos` | Lista planos persistidos ou cria/retoma plano dos setores e horizonte salvo |
| GET/PUT | `/api/pcm/planos/{id}` | Carrega plano ou valida e salva revisão (409 em alteração concorrente) |
| POST | `/api/pcm/planos/{id}/sugerir` | Sugere alocação PM/corretiva sem persistir ou confirmar |
| POST | `/api/pcm/exportar` | Excel da seleção filtrada de OTs da carteira PM/corretiva |
| GET | `/api/pcm/planos/{id}/revisoes` | Histórico imutável com motivos e datas |
| GET | `/api/pcm/planos/{id}/revisoes/{revisao}/pdf` | PDF arquivado da revisão |

## Modelo da planilha

Coluna obrigatória:

- `Nº OT BMA`

Exemplos de outras colunas (detectadas automaticamente):

- Equipamento
- Descrição
- Local

Somente as linhas **sem** número de OT entram no JSON.

## Banco SQLite

Tabela `arquivos_processados`:

- `id`
- `nome_arquivo`
- `data_upload`
- `total_registros`
- `registros_processados`

Campos extras usados pela aplicação: `registros_ignorados`, `json_resultado`, `status`.

## Próxima etapa (não implementada)

`backend/services/BMAService.py`

```python
def criar_ot(self, dados_json):
    pass
```

Reservado para:

- Integração SharePoint
- Automação Selenium
- Criação automática de OT no BMA
