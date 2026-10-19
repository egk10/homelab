O Immich usa `/var/lib/immich/data` no ext4 do Cloudvero como armazenamento
principal. O backup mantém três repositórios restic criptografados e versionados,
sem contratar serviços: disco ext4 do minitx, disco ext4 do eliedesk e o bucket
privado Ceph RGW `immich-backups`. Os dois ext4 são independentes dos pools Ceph;
não há comprovação de distância geográfica entre as máquinas.

O minitx é o executor principal, sempre ligado, com backup a cada hora no minuto
15. O eliedesk é o executor de reserva, no minuto 45. Os timers são de usuário e
o linger de `egk` está habilitado nos dois hosts. A configuração de papel fica em
`~/.config/immich-backup-worker.env`: `IMMICH_BACKUP_WORKER=minitx` ou
`IMMICH_BACKUP_WORKER=workstation`. O código rejeita papel errado no minitx e não
faz SFTP para o próprio host.

| Executor | Repositórios exigidos | Cópia adicional |
|---|---|---|
| minitx | ext4 local e Ceph S3 | eliedesk, quando disponível |
| eliedesk | ext4 local e SFTP minitx | Ceph S3 |

A cópia local é feita primeiro e fica registrada em `last-local-media.json`.
Uma falha de destino nunca remove essa cópia. `last-media.json` só avança quando
os dois destinos exigidos pelo papel concluírem. `last-report-media.json` registra
cada destino, inclusive falhas opcionais, com campos `worker`, `worker_host`,
`required_repositories`, `repository_status` e timestamps. O minitx espelha seus
relatórios no eliedesk como `minitx-last-media.json` e
`minitx-last-report-media.json`; o monitor também deve consultar o minitx vivo,
pois o desktop pode estar desligado. Todos ficam em
`~/.local/state/immich-backup/`. `last-attempt.json` registra running/ok/failed e a
classe sanitizada do erro. O monitor deve alertar backup com mais de duas horas.

`python3 immich_backup.py` captura só banco, inventário e configuração.
`python3 immich_backup.py --media` acrescenta os arquivos. No minitx, informe o
papel também na execução manual. Um snapshot PostgreSQL exportado e somente de
leitura mantém `pg_dump` e inventário CSV na mesma visão, sem parar uploads.
O banco é capturado antes dos arquivos. Rsync usa `--checksum` e nunca `--delete`.
Exclusões/limpezas concorrentes devem ser pausadas durante um backup consistente.

A auditoria separa a fonte do cache: cada original na fonte é lido integralmente
e comparado pelo SHA1 ao inventário do banco. `source_verified`, `source_missing`
e `source_integrity_errors` descrevem o armazenamento principal. `verified` e
`missing` descrevem os originais recuperáveis no staging. `cache_recovery_available`
conta arquivos em cache cujo original desapareceu da fonte; isso preserva a
recuperação e não esconde a perda. Erros de leitura/hash falham o job.
Um relatório falho com essas contagens é publicado antes da interrupção, sem
snapshots falsos. `source_checked_at` registra o fim da auditoria em UNIX seconds;
o monitor usa essa ordem para comparar o primário entre os dois executores,
independentemente da disponibilidade de cópias anteriores. Arquivos
historicamente ausentes mantêm `library_complete=false`. Os detalhes ficam em
`source-asset-integrity.json` e `asset-integrity.json` dentro de cada snapshot.

Depois dos dois destinos exigidos concluírem, a limpeza remove apenas arquivos
próprios do staging que não constam nem na árvore atual da fonte nem no inventário
capturado. Originais ainda referenciados pelo banco permanecem protegidos. Os
arquivos da fonte e snapshots não são apagados por essa limpeza. A retenção
semanal guarda 30 snapshots diários, 12 semanais e 12 mensais de mídia por repo;
snapshots metadata-only anteriores à migração são preservados. Arquivos excluídos
podem permanecer nos históricos até essa retenção vencer.

A senha restic é estável, criada uma única vez, em
`~/.local/state/immich-backup/restic-password`, modo 0600. O minitx recebeu uma
cópia de recuperação em `recovery-password`; seu primeiro executor adotou essa
mesma chave e jamais gera uma substituta para repo existente. Diretórios privados
usam 0700. A senha, credenciais RGW e apenas o arquivo de chave API do monitor
entram no staging privado 0600 e são arquivados criptografados. A configuração
inclui `.env`, compose, serviço systemd Immich e override Ceph existente. Os
administradores dos hosts que guardam a chave conseguem decriptar seus repos.

O bucket Ceph é acessado diretamente por S3 usando túnel SSH temporário
`127.0.0.1:17480 -> cloudvero:127.0.0.1:7480`, sem S3FS. O código cria somente
`immich-backups` após HEAD 404 e verifica ACL privada; não modifica objetos em
`immich-uploads`. Credenciais existentes do RGW são lidas privadamente e guardadas
0600. No minitx, operações de gestão do bucket usam o boto3 já instalado no
Cloudvero, por helper que permite apenas quatro operações e esse bucket.
Não foi instalado AWS CLI nem feita atualização geral de pacotes no minitx.
O restic copiado é 0.18.1, SHA256
`a149fe88aba426a78692316f94e2d6bbbadf7a4d50a03a4c44c478c88347c50b`;
a compatibilidade glibc e a execução foram verificadas.

`python3 immich_restore_test.py --cleanup` restaura o repo local em um diretório
privado único, compara hash do dump, importa integralmente em PostgreSQL isolado
sem rede/portas e com tmpfs, confere a contagem de ativos e hashes de todos os
originais disponíveis. `--secondary` escolhe SFTP e `--ceph` escolhe o cluster.
A imagem do banco usa o digest real arquivado no snapshot. O teste nunca monta
banco de produção nem inicia o aplicativo. Sem `--cleanup`, preserva os arquivos
restaurados; com essa opção, remove só seu diretório recém-criado após registrar
prova JSON. Mensalmente, cada papel testa AMBOS os destinos exigidos: minitx às
06:30 do dia 1, eliedesk às 08:30. O monitor exige ambas as provas com até 35 dias.
O minitx espelha também `minitx-last-restore-media.json` e
`minitx-last-restore-media-ceph.json` no desktop quando disponível.

As units estão nesta pasta. Só ativá-las depois das primeiras provas completas e
da execução minitx serem revisadas. O timer principal do minitx é
`immich-backup-minitx.timer`; no eliedesk, `immich-backup.timer`. A unit usa retry
após dez minutos, limitado a três starts em 45 minutos, permitindo a próxima hora.
O erro continua visível em `journalctl --user -u immich-backup.service`.

A chave SSH dedicada minitx -> eliedesk tem fingerprint
`SHA256:Xfv+xovSvO4GK4LSBISQI/QEqDrILJIPRd76am5TBMA`. Somente a chave pública foi
adicionada a `~/.ssh/authorized_keys` do eliedesk, com `restrict` e
`from="100.72.3.103"`, IP Tailscale conferido. A privada permanece no minitx.
Para revogar, remover somente a entrada comentada `immich-backup-minitx-worker`
com esse fingerprint, preservando todas as outras entradas. Isso afeta apenas a
cópia opcional para o desktop; acesso Cloudvero e backup minitx/Ceph permanecem.

Referências oficiais:
- https://docs.immich.app/administration/backup-and-restore/
- https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html
- https://restic.readthedocs.io/en/stable/040_backup.html
