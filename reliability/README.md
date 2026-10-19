# Recuperação e confiabilidade do Immich — 2026-10-05

Endereço: <https://immich.velociraptor-scylla.ts.net>.
Vaultwarden: <https://vaultwarden.velociraptor-scylla.ts.net>.

## Diagnóstico confirmado

O Immich dependia de um ponto de montagem S3FS indisponível. O Ceph tinha apenas
dois monitores, e um deles havia parado; os serviços atingiram o limite de
tentativas do systemd e permaneceram falhos. Havia também registros de fotos e
vídeos sem um original integralmente legível. Não foi comprovada a causa histórica
da ausência desses objetos; PGs saudáveis não comprovam a integridade lógica da
biblioteca do Immich.

O inventário inicial tinha 811 arquivos. A extração completa validou 619 originais
por SHA-1. A leitura do celular antigo recuperou outros 113, sem modificar o
celular ou apagar registros: 732 originais disponíveis e 79 ainda ausentes
(64 vídeos e 15 fotos). A procura por nomes, tamanhos e hashes no celular antigo,
e por candidatos no bucket preservado do Nextcloud, não encontrou esses 79.
Os registros ausentes foram preservados para novas tentativas de recuperação.
Após o Ceph terminar a recuperação, uma segunda tentativa dos 79 originais
não recuperou arquivos adicionais: 60 retornaram 404 e 19 falharam na leitura
integral. Esse resultado não comprova perda definitiva em outras fontes.

## Mudanças aplicadas

- Immich 2.4.1 preservado e fixado na versão que já estava em execução.
- Biblioteca ativa em `/var/lib/immich/data`, ext4 no Cloudvero, sem dependência
  de S3FS. Os caminhos armazenados no banco permaneceram iguais.
- `homelab-immich.service` habilitado, com novas tentativas de inicialização;
  container com healthcheck. Atualização automática desse container desativada.
- Nextcloud e seu banco parados, restart desativado, perfil de compose desativado
  e anúncio na tailnet removido. Seus dados e bucket foram preservados.
- Três monitores Ceph em quorum, dez OSDs UP/IN, 721 PGs active+clean em duas
  verificações consecutivas. Serviços recuperados e retomada automática ajustada.
  Alerta percentual MON_DISK_LOW preservado; nenhum disco foi formatado.
- Backups criptografados e versionados em ext4 no computador e no minitx,
  independentes dos pools Ceph, além de uma cópia no bucket `immich-backups`.
  O bucket antigo `immich-uploads` foi preservado. O novo bucket recebe backups
  Restic; o Immich grava primeiro na biblioteca local do Cloudvero.

## Provas e operação

O backup captura o banco e o inventário na mesma transação PostgreSQL, verifica
o SHA-1 dos originais e só registra sucesso dos repositórios obrigatórios após
terminar as cópias. A restauração usa um PostgreSQL isolado, sem rede ou acesso
ao banco de produção. Ausências históricas são explicitadas, nunca ocultadas
como biblioteca completa.

- [Backup e restauração](backup/README.md)
- [Monitor e teste de envio](monitor/README.md)
- [Ceph e evidências de recuperação](ceph/IMPLEMENTATION.md)

Relatórios privados: `~/.local/state/immich-backup/last-*.json`.
As chaves de recuperação estão em diretórios privados no computador e no minitx;
seus valores não devem ser publicados. A recuperação completa exige arquivos,
banco, configurações e chave de criptografia.

Antes de excluir fotos dos celulares, verificar a conclusão do envio e dos
backups. A conexão USB permite recuperar arquivos já registrados no banco, mas
não comprova que o backup automático do aplicativo está ativo. A sincronização
real dos álbuns selecionados dos dois celulares foi confirmada pelo usuário;
a busca dos 79 originais restantes continua pendente. Não há comprovação de
independência geográfica/energética dos
destinos; esta instalação não oferece uma garantia equivalente à do Google Fotos.

## Validação final

As três primeiras cópias completas e suas restaurações passaram: 811 registros,
732 originais conferidos e 79 ausências históricas explícitas. O teste sintético
também passou envio, download com SHA-1, backup, restauração e exclusão confirmada
da sua linha e arquivo. O mesmo PNG de 914 bytes foi lido de seu snapshot Ceph
após a exclusão na aplicação e teve seu SHA-1 confirmado. Isso testa o pipeline
do servidor; não comprova backup automático dos celulares.

O worker minitx fez cópias completas e incrementais nos três destinos, com
auditoria SHA-1 adicional diretamente no armazenamento ativo. As restaurações
local e Ceph no minitx passaram. Seu serviço systemd de backup executou com
`Result=success` e código 0. Os serviços reais de monitor também passaram nos
dois hosts. Ao fim da primeira recuperação havia aproximadamente 55 GiB livres;
após os envios dos celulares, foram observados aproximadamente 46 GiB livres.

Nove timers estão habilitados e ativos:

- minitx: backup horário no minuto 15, retenção semanal, restauração mensal dos
  dois repositórios obrigatórios e monitor a cada 15 minutos. Os timers próprios
  desse host usam os nomes `immich-backup-minitx.timer`,
  `immich-restore-test-minitx.timer` e `immich-monitor-minitx.timer`.
- eliedesk: backup horário no minuto 45, retenção semanal, restauração mensal,
  monitor a cada 15 minutos e E2E sintético diário às 06:15, com até 5 minutos
  de variação. O próximo E2E observado é 06/10/2026 às 06:17 EDT. Esse teste
  depende de o computador estar ligado; não executa testes acumulados ao religar.

O backup e o monitor do minitx continuam funcionando quando o eliedesk está
desligado. `Linger=yes` foi confirmado nos dois hosts. O E2E coordena a exclusão
do seu único arquivo com os locks de ambos os workers, evitando interferir na
captura de um backup. O cluster continua com 3 monitores, 10 OSDs UP/IN e
721 PGs limpos; permanece somente o aviso percentual MON_DISK_LOW no eliedesk.

Verificar os agendamentos de cada host com
`systemctl --user list-timers --all 'immich*'`. Relatórios privados de monitor
ficam em `reliability/monitor/state.json` e os de backup em
`~/.local/state/immich-backup/`. Inventários privados e evidências operacionais
foram excluídos do controle de versão por `.gitignore`; nenhum commit ou push
foi feito neste checkout que já continha alterações de outras frentes.

Continuação móvel em 05/10: o Pixel 10a conseguiu entrar após permitir acesso
às fotos/vídeos e reabrir o aplicativo. O Motorola moto g 5G entrou ao conectar
o Tailscale à mesma tailnet. Os dois ficaram online simultaneamente, e o usuário
informou fila de backup zerada nos dois aparelhos. A conta passou de 811 para
1550 registros, incluindo 136 arquivos com data de captura entre janeiro e
março de 2026, que antes não constavam no banco. Isso comprova os envios
observados e a fila dos álbuns selecionados, não todos os arquivos de cada
aparelho nem seu funcionamento futuro em segundo plano.

A busca por cabo preservou 675 cópias exatas em
`/home/egk/immich-phone-recovery` e usou 113 para repor originais de registros
existentes. Os demais arquivos copiados já correspondiam a originais disponíveis.
Essa etapa procurava arquivos já registrados no servidor; novos registros das
fotos de 2026 entraram pela sincronização do aplicativo. Nenhum arquivo foi
excluído do Motorola durante a recuperação.

As três cópias do lote de 1260 registros passaram, com 1181 originais
conferidos e 79 ausências históricas. Um snapshot anterior, de 1238 registros,
também restaurou banco e 1159 originais integralmente nos repositórios ext4 e
Ceph do minitx. O backup dos 1550 registros posteriores ao Motorola conferiu
1471 originais na fonte e no staging, com zero erros de hash/leitura e as mesmas
79 ausências históricas. As cópias nos três repositórios concluíram com sucesso.
O teste adicional leu diretamente desse snapshot Ceph uma foto de janeiro,
uma de fevereiro e uma de março de 2026; os três tamanhos e hashes SHA-1
conferiram. A consulta limitada aos diretórios escolhidos passou após a primeira
tentativa atingir o limite de tempo. Essa prova cobre as três fotos selecionadas;
as restaurações integrais anteriores permanecem comprovadas, sem atribuir uma
restauração integral ao novo snapshot. A busca pelos 79 originais históricos
restantes continua pendente.
