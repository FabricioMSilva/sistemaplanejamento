# Planning & Scheduling - distribuicao Windows

## Estado desta implementacao

- Launcher Windows sem console, icone na bandeja e controle dos processos implementados.
- Instalador Inno Setup configurado por usuario, SEM elevacao de administrador.
- Frontend standalone de producao compilado e integrado com FastAPI em portas locais privadas.
- Testes de paths, launcher, proxy HTTP e configuracao sem administrador disponiveis.
- A execucao inicial do extrator na pasta do repositorio foi bloqueada pela politica
  corporativa. O usuario confirmou `C:\BUSAPPS` como local autorizado pela TI; a
  geracao foi retomada nesse diretorio com a opcao `-BuildDirectory`.
- O executavel congelado, o instalador final e sua execucao em Windows limpo ainda
  precisam ser gerados e validados em ambiente de build autorizado. O build completo
  exige os testes congelados antes de produzir o Setup.

## O que o funcionario recebe

Um unico arquivo versionado, por exemplo `dist/Planning-Scheduling-Setup-1.0.0.exe`.
O funcionario nao instala Python, Node.js, npm, pip, Selenium, GeckoDriver ou VS Code.
O Windows precisa ser Windows 10/11 x64 compativel e permitir a execucao da aplicacao.
O acesso ao BMA/SharePoint continua exigindo rede, identidade e permissoes corporativas.

O instalador apresenta MICHELIN / Planning & Scheduling / Centro Operacional,
cria o atalho no Menu Iniciar e oferece um atalho opcional na Area de Trabalho.
O atalho inicia os servicos sem console e abre a interface no navegador padrao.
O icone na bandeja oferece abrir a interface, autenticar BMA, abrir logs e encerrar.
Fechar a aba do navegador nao encerra o aplicativo; use Encerrar na bandeja.

## Sem administrador

- `PrivilegesRequired=lowest`, sem opcao de elevar privilegios.
- Programa: `%LOCALAPPDATA%\Programs\Michelin\PlanningScheduling`.
- Atalhos e desinstalador pertencem apenas ao usuario atual.
- Nao cria servico Windows, tarefa global, regra de firewall ou registro em HKLM.
- Nao adiciona Python/Node/Firefox ao PATH nem altera o navegador padrao.
- Atualizar/desinstalar nao apaga automaticamente os dados pessoais da aplicacao.

AppLocker, WDAC, antivirus e politicas de execucao ainda podem bloquear o instalador
ou o aplicativo. Instalacao sem administrador nao contorna essas politicas. A TI
deve homologar/permitir a distribuicao e assina-la com certificado corporativo.

## Conteudo e arquitetura

- PyInstaller onedir com Python, FastAPI/Uvicorn, Selenium e dependencias reais
  do backend, inclusive pandas, bibliotecas nativas, Excel, SQLite, Pillow e ReportLab.
- Next.js standalone e Node.js privado, sem npm/pip no computador do funcionario.
- Firefox ESR pt-BR e GeckoDriver fixados em `vendor-lock.json` e incluidos no pacote.
- Assets Michelin, catalogos JSON, worker PDF, arquivos estaticos e licencas.
- `database/data/funcionario.json` segue no pacote como cadastro de referência
  necessário aos vínculos SharePoint/BMA; uma cópia local do usuário tem precedência.
- Nenhuma copia da raiz do repositorio, do banco operacional ou de uploads entra no pacote.
- Sem `.env`, perfil autenticado, cookies, senhas, tokens ou credenciais do desenvolvedor.

O launcher escolhe portas livres, vincula os dois servicos a 127.0.0.1 e usa um
token efemero de backend. O Next encaminha chamadas `/api/desktop/api/...` somente
para o backend privado, preservando uploads e downloads por streaming. Requisicoes
cross-site e Host/Origin indevidos sao rejeitados. O token nao vai no JavaScript
do navegador nem e persistido no arquivo de estado. Trafego loopback nao usa proxy.

So uma instancia por sessao Windows fica ativa. Abrir outro atalho reabre a interface.
O launcher testa a saude real dos dois servicos antes de abrir o navegador e usa um
Windows Job Object para encerrar backend, Node, GeckoDriver e Firefox ao sair.

## Dados, logs e autenticacao

Tudo gravavel da instalacao fica em `%LOCALAPPDATA%\Michelin\PlanningScheduling`:

```text
database/data/bma_intranet.db   SQLite: OTs, equipes, planos, revisoes e PDFs
backend/uploads/               Uploads e diagnosticos/capturas BMA
backend/uploads/bma_leitura/   Log de envio BMA
logs/                         Logs do launcher, backend e frontend
FirefoxProfile/               Perfil exclusivo DESTE usuario, criado vazio
running.json                  Somente URL local para reabrir a instancia
```

O Firefox do pacote nunca usa um perfil pessoal ou o perfil do desenvolvedor.
Usa caminhos absolutos para o navegador/driver; nao usa Selenium Manager nem baixa
drivers na execucao instalada. A primeira operacao pode abrir Firefox visivel para
login/MFA, embora a automacao normalmente seja oculta. Autenticar BMA na bandeja
permite renovar a sessao; apos concluir o login, tente novamente a operacao.
O login SharePoint pode ser solicitado ao atualizar mao de obra NF.
Nao se contorna MFA, nem se pressupoe que login sera permanente.

O perfil persistente e protegido contra operacoes concorrentes. Enquanto uma OT
estiver aberta para consulta, conclua/feche essa janela antes de outra operacao BMA.
Se uma sessao oculta expirar, use a autenticacao interativa da bandeja.
O Firefox dedicado nao se atualiza sozinho; mantenha navegador e driver atualizados
por novas versoes homologadas do instalador, atualizando os hashes oficiais.

Os dados continuam LOCAIS e separados por funcionario/computador. Nao ha sincronizacao
automatica entre instalacoes. Backups e transferencia devem usar meios autorizados.

## Gerar o instalador: somente na maquina de build

Requisitos do responsavel pelo build, NAO do funcionario:

- Windows x64, Python 3.11+ x64 e Node.js 22/24 LTS x64 com npm.
- Acesso aos repositorios oficiais PyPI/npm, Mozilla, Node.js e GitHub.
- Certificados corporativos confiaveis configurados; nao desabilite verificacao TLS.
- 7-Zip e Inno Setup permitidos pela politica corporativa. Verifique a licenca de
  uso comercial do Inno Setup com a empresa antes de distribuir.

Na raiz do projeto, em PowerShell autorizado:

```powershell
.\distribution\windows\build.ps1
```

Quando a TI indicar `C:\BUSAPPS` como local autorizado para ferramentas de build:

```powershell
.\distribution\windows\build.ps1 -BuildDirectory 'C:\BUSAPPS\PlanningSchedulingBuild'
```

`-NodeExe` permite informar o caminho do Node.js homologado quando ele nao estiver
no PATH. A opcao de build nao muda o local de instalacao nem os dados do funcionario.

Por padrao usa o Python do backend apenas para criar um venv de build separado.
Para ferramentas JA homologadas pela TI, informe seus caminhos:

```powershell
.\distribution\windows\build.ps1 `
  -PythonExe 'C:\FerramentasHomologadas\Python\python.exe' `
  -SevenZipExe 'C:\FerramentasHomologadas\7-Zip\7z.exe' `
  -InnoCompiler 'C:\FerramentasHomologadas\Inno Setup\ISCC.exe' `
  -AppVersion '1.0.1'
```

Sem caminhos explicitos, o build tenta baixar/verificar ferramentas oficiais e
preparar o compilador Inno SOMENTE por usuario. Se houver bloqueio corporativo,
pare e use o fluxo autorizado da TI. Nao renomeie/copiei ferramentas para burlar regras.

O build usa `build/windows/venv`, uma copia permitida do frontend e uma lista
explicita de recursos. Nao substitui `frontend/node_modules` nem `frontend/.next`.
Os downloads ficam em cache e sao verificados por SHA-256/SHA-512; Node deve ter
assinatura oficial valida. As versoes, hashes dos arquivos e inventarios de
dependencias ficam em `distribution-manifest.json` e arquivos de inventario.
Os downloads de ferramentas sao apenas para a maquina de build.

## Atualizacoes

O metodo implementado e executar um novo `Planning-Scheduling-Setup-VERSAO.exe`, sem
desinstalar a versao anterior e sem administrador. Nao existe download automatico
de atualizacoes nesta implementacao.

- Incremente `-AppVersion`, por exemplo de `1.0.0` para `1.0.1`, em cada release.
- Mantenha o AppId do instalador; ele identifica a mesma aplicacao em todas as versoes.
- O instalador conserva pasta e escolhas anteriores de atalhos, e rejeita downgrade.
- Antes de atualizar, salve o planejamento, conclua operacoes BMA e use Encerrar
  na bandeja. O instalador nao deve terminar automaticamente uma operacao BMA ativa.
- Somente diretorios de componentes dentro de `{app}` sao substituidos; o banco,
  uploads, logs e perfil BMA do usuario ficam fora dessa pasta e nao sao removidos.
- Mudancas futuras no esquema do banco exigem backup e migracao testada antes da
  distribuicao. A simples preservacao do arquivo nao garante compatibilidade futura.

Antes de compilar Setup, o build executa no executavel congelado:

1. `--self-test`: banco vazio isolado, catalogos, PDF com logo e Firefox/GeckoDriver
   reais, sem acessar BMA nem utilizar perfis de pessoas.
2. `--smoke-test`: frontend e backend reais do pacote, proxy, paginas, catalogos,
   ausencia de dados operacionais e bloqueio de chamadas nao autorizadas.

Depois de gerar, a TI deve assinar launcher e instalador no pipeline corporativo,
recompilando o instalador para incluir o launcher assinado. Nao ha certificado
privado nem segredo de assinatura neste repositorio.

## Validar partes sem gerar o instalador

```powershell
node .\distribution\windows\build_frontend.cjs .\build\windows standalone
.\backend\.venv\Scripts\python.exe .\distribution\windows\validate_source.py
node --test .\frontend\tests\desktopDistribution.test.cjs
```

`validate_source.py` usa backend de desenvolvimento + frontend standalone em portas
temporarias, SEM abrir BMA e com banco descartavel. Aceita `--node` com o caminho
do Node autorizado. Resultado: `build/windows/source-runtime-validation.json`.
Essa validacao nao deve ser confundida com validacao do pacote congelado.

## Desenvolvimento permanece separado

Os comandos existentes de Uvicorn e `npm run dev` continuam funcionando.
Sem `BMA_DESKTOP`, a descoberta de Firefox/Selenium Manager permanece como antes.
Sem `BMA_DATA_DIR`, banco e uploads permanecem nos caminhos originais do projeto.
O build desktop usa `.next-desktop` e configuracao TypeScript separada; o modo dev
mantem `.next` e as URLs de API existentes.

## Homologacao obrigatoria antes da entrega

Validar em VM/Windows limpo com conta padrao, SEM Python/Node/VS Code/Firefox previo:

1. Instalar, atualizar e desinstalar SEM UAC; conferir atalhos apenas do usuario.
2. Abrir por atalho sem console; abrir novamente e confirmar instancia unica.
3. Confirmar navegacao, temas, uploads, Excel e visualizacao/download de PDF.
4. Autenticar BMA/SharePoint com identidade de teste autorizada, inclusive MFA.
5. Validar coleta e envio BMA reais com autorizacao e escopo controlado.
6. Confirmar preservacao dos dados em atualizacao e separacao entre contas Windows.
7. Encerrar na bandeja e confirmar que os processos filhos terminaram.
8. Verificar assinaturas, antivirus, licencas, backups e politica de distribuicao da TI.

Ainda nao foi possivel executar essa homologacao nesta maquina. Um teste existente
de abertura de OT tambem falha com o BMAService original; essa falha nao foi alterada
nem escondida pela implementacao de distribuicao.