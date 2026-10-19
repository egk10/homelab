# Ensaio de atualização e login móvel — 2026-10-05

O aplicativo Android 3.2.1 no celular novo apresentou erro genérico no login,
mas o usuário confirmou acesso com as mesmas credenciais no navegador dele.
Depois de permitir fotos/vídeos e fechar/reabrir o aplicativo, confirmou que
conseguiu entrar. Essa sequência resolveu o sintoma no aparelho novo; não
distingue qual das duas ações eliminou a falha. O servidor permanece na
versão 2.4.1. O Motorola antigo conseguiu entrar após conectar o Tailscale
à mesma tailnet, e os envios de 2026 foram observados no servidor.

O código oficial aceita o aplicativo v3 com servidor v2. A diferença de versões
não comprovou a causa do erro. O celular não estava conectado ao computador
durante este diagnóstico; não foi possível coletar registros nativos.

Foi feito backup novo do banco/configuração nos três repositórios antes de
qualquer mudança de produção. Nenhuma senha de usuário foi modificada e não
houve migração do banco de produção.

## Ensaio isolado

O banco copiado foi restaurado em tmpfs, com rede Docker interna, nenhuma porta
publicada e mídia vazia. A sequência 2.4.1 → VectorChord → 3.2.1 preservou os
811 IDs, caminhos, checksums e proprietários dos ativos do inventário inicial,
além das senhas das contas. Um novo pg_dump após a migração restaurou corretamente.
Isso valida esquema e configuração; não comprova os originais em produção.

- PostgreSQL: preservar major 16 e `PGDATA=/var/lib/postgresql/data/pgdata`.
- Imagem ensaiada: `ghcr.io/immich-app/postgres:16-vectorchord0.4.3-pgvectors0.3.0`
  com digest `sha256:0851d187e1f512300b3fcf7911641aa94075a3bfe457f2600ec8637ca1cb9139`.
- Remover o comando antigo com `shared_preload_libraries=vectors.so` e usar
  a configuração padrão da imagem oficial. Migrar primeiro com servidor 2.4.1.
- Declarar `IMMICH_MEDIA_LOCATION=/usr/src/app/upload`, mantendo o bind local
  e os caminhos existentes no banco.
- Servidor ensaiado: `ghcr.io/immich-app/immich-server:v3.2.1`, digest
  `sha256:2ab6a6273755d9b8a5c4f25dbaa2d097fc4a2cc261b70bc73621e6405cc106fe`.

Os relatórios privados nesta pasta registram os ensaios de migração e API.
O monitor agora consulta a versão antes de iniciar o teste sintético: mantém
os campos deviceId/deviceAssetId em v2 e os omite em v3. Nos dois ambientes
isolados, upload 201, download 200 com SHA1, exclusão 204 e os três escopos da
chave passaram. Versão indeterminada impede novo upload. O código foi promovido
ao minitx com hash idêntico e os monitores reais dos dois hosts passaram.

## Sincronização real

Após o login do celular novo, a contagem de ativos reais subiu de 811 para 1260
e o último envio observado foi às 20:03:29 UTC. O usuário informou 349 itens
e nenhum pendente no aplicativo do novo aparelho. Esse total representa sua
seleção no aplicativo, não uma contagem auditada de todos os arquivos dos dois
celulares. O backup principal foi acionado para conferir os novos originais
e arquivar um snapshot consistente. As 79 ausências históricas continuam sendo
tratadas separadamente; novos envios não comprovam sua recuperação. Nesse ponto,
as fotos do início de 2026 no Motorola ainda precisavam ser sincronizadas.

Na visão da tailnet às 20:13 UTC, o único peer Android era o Pixel 10a,
conectado. Não havia um Motorola listado. O usuário foi orientado a conectar
o Tailscale no Motorola à mesma tailnet antes do login, e foram solicitados
o resultado do navegador nesse aparelho e as versões de Android/Immich.
O banco confirmou zero ativos da conta com `fileCreatedAt` entre janeiro e
março de 2026. Dois logins simultâneos são permitidos: AuthService cria novas
sessões sem invalidar as anteriores.

O primeiro snapshot após o envio do novo aparelho capturou 1238 registros:
1159 originais passaram SHA1 na fonte e no staging, com 79 ausências
históricas e zero erros de hash/leitura. Portanto esse lote validou 427
novos originais. Esse lote concluiu nos três destinos e restaurou integralmente
o banco e 1159 originais nos repositórios local e Ceph do minitx. A biblioteca
chegou a 1260 durante o snapshot; os 22 registros posteriores foram incluídos
no backup seguinte do eliedesk, com 1181 originais verificados e três
repositórios concluídos. As provas de cada lote devem permanecer associadas
ao seu snapshot.

Depois de conectar o Motorola, o servidor passou a 1550 registros e 136 arquivos
com data de captura entre janeiro e março de 2026. O usuário confirmou restante
0 no Motorola; o novo backup foi capturado com 1550 registros e conferiu 1471
originais na fonte e no staging, com zero erros de hash/leitura e 79 ausências
históricas. As cópias nos três destinos concluíram com sucesso.
Uma prova adicional leu desse snapshot Ceph três originais, um de cada mês
(janeiro, fevereiro e março de 2026), com tamanho e SHA-1 conferidos. A primeira
execução atingiu o limite de tempo; a consulta limitada aos diretórios escolhidos
passou. Isso é amostragem, separada das restaurações integrais.

Referências oficiais:

- https://docs.immich.app/install/upgrading/
- https://immich.app/blog/v3-migration
- https://github.com/immich-app/immich/tree/v3.2.1/mobile
