# Mentor de aula — handoff de execução (2026-09-11)

Documento para retomar a execução em outra janela de contexto. Fonte da verdade do progresso são os **ledgers** (git-ignored, mas persistentes em disco) de cada plano; este documento consolida o estado, o que falta e todas as decisões tomadas em nome do usuário.

## 0. Atualização 2026-09-11 (sessão 2) — ambiente destravado, tudo executado

Esta seção substitui o que as seções 1–4 diziam sobre "escrito, não executado". Ledgers seguem sendo a fonte da verdade.

### Estado por plano
| Plano | Repo | HEAD | Estado |
| --- | --- | --- | --- |
| A — rotas internas | borderless-api | `be6d30ba` | COMPLETO. Suíte unitária 3577/3577 verde. Rotas verificadas ao vivo: 401 sem/erro de segredo; lista de `program-base` (2 aulas do seed); 404 vídeo inexistente; rota de mídia devolve 502 legível ("Panda Video API request failed: 401 Unauthorized"). **Verificação ao vivo do Panda BLOQUEADA: a `PANDA_VIDEO_API_KEY` do `.env` responde 401 no Panda (também via curl direto), e todos os vídeos do seed têm `providerRef` vazio.** |
| B — ingestão | oracle-borderless | `f066ed0` | COMPLETO. `alembic upgrade head`/`check` OK nos dois bancos; ciclo `downgrade 0011 → head` OK; índices esperados presentes (`ix_lesson_chunks_embedding_hnsw` hnsw `vector_cosine_ops`); `tests/integration` 144 OK; suíte total 741 OK. CLI `mentor:ingest program-base --limit 1` percorre sync→claim→mídia e falha legível (502 do Panda), lote continua, `failure_reason`/`attempts=1` gravados. Ingestão real depende da chave do Panda. |
| C — modo mentor | oracle-borderless | `f066ed0` | COMPLETO. 4 testes de integração escritos offline falharam na 1ª execução — todos defeitos de TESTE (Ruling C9), corrigidos em `d2786cd..cece091`, re-revisão limpa. Verificado ao vivo (Oracle 8000): status pending/failed/unknown/401; turno mentor real com `search_lesson`, 2 citações `source_type=lesson` `?t=0`/`?t=275`; fora do assunto responde com aviso e grava `lesson_coverage=gap`; traces com intent/lesson_id/embedding; `/ops/mentor` 200 na allowlist e 404 fora; log sem "search_lesson tool failed"/"non-checked-in". |
| D — aba Mentor | borderless-platform | `79375686` | COMPLETO. Fix wave (C1–C3, I1–I6, minors) + re-revisão limpa; e2e executado pela 1ª vez: 3 falhas em `mentor-citation.spec.ts` → fix round 1 (seletor ambíguo "Sources"/"Resources" + BUG REAL: navegação só-de-query na mesma rota pendurava o App Router → citação da mesma aula aplica `?t=` via History API). `--project=oracle e2e/tests/oracle`: **56 passed / 0 failed** (reexecutado pelo controller). Demo automatizada contra o Oracle REAL passou (aba só em aula ready, Fontes, link interno `?t=`, URL atualiza, 400px, 2º turno, failed→"indisponível", unknown→sem aba). Re-revisão escopada da rodada 1 (opus): 5/5 ADDRESSED, nada aberto. |

### Como o ambiente foi destravado (sem Docker, sem sudo)
Postgres 16.2 + pgvector 0.6.2 via pacote Python `pgserver` (venv 3.12), dados em `~/.local/share/borderless-pg/{oracle,api}` (5432 oracle/oracle; 5433 postgres/postgres, db `borderless_dev`), socket dir `~/.local/share/borderless-pg/sock`; ffmpeg/ffprobe 7.0.2 estáticos em `~/.local/bin`; Chromium do Playwright instalado. Subir: `pg_ctl -D <dir> -o "-p <porta> -k ~/.local/share/borderless-pg/sock -c listen_addresses=localhost" start`. `.env` locais (git-ignored) ganharam: API `MENTOR_INGEST_SECRET`; Oracle `MENTOR_ENABLED=true`, `BORDERLESS_INTERNAL_SECRET` (mesmo valor), `ADMIN_EMAILS=base@borderless.com`. Receita completa na memória do Claude (`local-env-without-docker`).

### Aula da demo
`b652bb2c…` (`base-construindo-portfolio`) está READY no banco dev do Oracle com **transcrição SINTÉTICA rotulada** ("[TRANSCRIÇÃO SINTÉTICA PARA DEMO]…", 2 chunks, embeddings reais) — só para exercitar o fio enquanto o Panda está bloqueado. Rodar `mentor:ingest program-base --lesson base-construindo-portfolio --force` assim que houver chave válida substitui o conteúdo. `186cad2e…` (`base-mindset-global`) está `failed` (Panda 401).

### O que fica para o usuário
1. **Chave do Panda**: renovar `PANDA_VIDEO_API_KEY` (e confirmar que as aulas do Base têm `providerRef`) → `curl …/media | ffprobe` → `mentor:ingest program-base --limit 1` 2x (2ª = "sem mudança") → lote completo (~US$10). Só depois disso o seek do player (C3) tem cobertura e a demo usa conteúdo real.
2. **Merge/PR** dos três repos (`feat/speech-to-text`, sem upstream, nada pushado) — decisão do usuário; criar o secret `MENTOR_INGEST_SECRET` no GitHub Actions antes do deploy da API.
3. **Follow-ups técnicos** (parked, com rulings nos ledgers): bug do App Router em qualquer link só-de-query (Ruling D10 — só a citação do mentor foi corrigida); `lessons.ts` mapeia body ilegível para `unknown` (com D9 a aba SOME em drift de schema — virar `isError`); M10: HNSW pós-filtra por `lesson_id` — busca exata por aula custa ~1 ms, considerar forçar caminho exato; testes de integração da API do Oracle gravam no banco DEV (não em `DB_NAME_TEST`); pergunta fora do assunto ainda mostra "Fontes" da aula (spec §10 sem limiar — decisão de produto); `evals/cases/mentor_set.json` sem task; `TabsContent` do mentor monta com trigger oculto; Vimeo `setCurrentTime` não verificado em runtime.
4. Apagar `.superpowers/sdd/*` dos três repos quando tudo estiver mergeado.

### Rulings desta sessão (C9, D9 já constava, D10) — íntegra nos ledgers
- **C9**: as 4 falhas de integração eram defeitos de teste; verificar se flush recusado no savepoint do trace custa a resposta → confirmado que NÃO (teste de cobertura adicionado) — custo se errado: nenhum.
- **D10**: correção do router (History API) restrita à citação da mesma aula; o resto vira ticket — custo se errado: outros deep-links só-de-query continuam pendurados até o follow-up.
- Controller (fora do fluxo de subagente, só docstring): removidas as notas "ESCRITO MAS NÃO EXECUTADO" de 3 testes já executados (`f066ed0`).

---

## 1. Estado por plano (branch `feat/speech-to-text` em cada repo, nada mergeado, nada pushado)

| Plano | Repo | Tasks | Revisão final | Estado |
| --- | --- | --- | --- | --- |
| A — rotas internas | borderless-api | 3/3 | feita + fix wave + re-revisão limpa | **COMPLETO em código** (HEAD `be6d30ba`) |
| B — ingestão | oracle-borderless | 7/7 | feita + fix wave + re-revisão limpa | **COMPLETO em código** (HEAD `ea2ca90` da fase) |
| C — modo mentor | oracle-borderless | 7/7 | feita + fix wave + re-revisão limpa | **COMPLETO em código** (HEAD `7300f45`) |
| D — aba Mentor | borderless-platform | 4/4 | **feita e CAPTURADA** em `borderless-platform/.superpowers/sdd/2026-09-11-mentor-platform/final-review.md` (With fixes: C1–C3, I1–I6) | tasks completas; falta o fix wave + re-revisão (HEAD `b2a5a8ea`) |

Ledgers: `borderless-api/.superpowers/sdd/2026-09-11-mentor-api/progress.md`, `oracle-borderless/.superpowers/sdd/2026-09-11-mentor-ingestao-oracle/progress.md`, `oracle-borderless/.superpowers/sdd/2026-09-11-mentor-modo-oracle/progress.md`, `borderless-platform/.superpowers/sdd/2026-09-11-mentor-platform/progress.md`. Cada um tem a varredura pré-voo, os rulings, os minors deferidos e uma linha `Task N: complete` por task (a regra de retomada da skill: task com essa linha NÃO se redespacha).

## 2. Como retomar (ordem)

1. Na nova janela, invocar `superpowers:subagent-driven-development` com o plano D (`borderless-platform/docs/superpowers/plans/2026-09-11-mentor-platform.md`). O ledger diz que as 4 tasks estão completas e a revisão final JÁ FOI FEITA e está gravada em `.superpowers/sdd/2026-09-11-mentor-platform/final-review.md` (não redespachar). Falta: UM fix wave com C1–C3, I1–I6 e os minors triados como FIX (ver arquivo; C3 — seek por efeito em `startSeconds` — é o item de trabalho real) → `review-package PLAN b2a5a8ea HEAD` → UMA re-revisão escopada → `PLANO D: COMPLETO`.
2. Subir o ambiente (seção 3) e executar a lista da seção 4 — **obrigatório antes de considerar B, C e D fechados**: migrations e testes de integração/e2e foram escritos e validados offline, nunca executados.
3. Só então `superpowers:finishing-a-development-branch` nos três repos (decisão de merge/PR é do usuário; branches sem upstream).
4. Apagar os workspaces `.superpowers/sdd/*` depois que tudo estiver fechado (o histórico git é o registro).

## 3. Bloqueios de ambiente (motivo de tudo que ficou "escrito, não executado")

- **Postgres**: não há servidor em `localhost:5432` (Oracle) nem o container `borderless-postgres:5433` (API/e2e). O binário `docker` existe via interop do Windows, mas o Docker Desktop estava parado / sem integração WSL para esta distro → abrir o Docker Desktop, Settings → Resources → WSL integration → ligar esta distro; `docker info` precisa responder.
- **ffmpeg/ffprobe**: ausentes; sem sudo nesta sessão → `sudo apt-get install -y ffmpeg`.
- **Segredos/flags**: `MENTOR_INGEST_SECRET` (API, ≥32 chars) == `BORDERLESS_INTERNAL_SECRET` (Oracle); `MENTOR_ENABLED=true` no `.env` do Oracle (kill switch, default False); `OPENAI_API_KEY` no Oracle; na plataforma `NEXT_PUBLIC_ORACLE_ENABLED=true`, `NEXT_PUBLIC_MENTOR_ENABLED=true`, `ORACLE_API_URL=http://localhost:8000` (NEXT_PUBLIC exige rebuild). Criar o GitHub Actions secret `MENTOR_INGEST_SECRET` antes de qualquer deploy da API.

## 4. Checklist consolidado do que rodar quando o ambiente subir

### 0. Pré-requisitos
- Docker Desktop aberto, integração WSL ligada para esta distro (`docker info` responde).
- `sudo apt-get install -y ffmpeg`.
- Segredos iguais nos dois lados: `MENTOR_INGEST_SECRET` (API, ≥32 chars) == `BORDERLESS_INTERNAL_SECRET` (Oracle). `MENTOR_ENABLED=true` no .env do Oracle. `OPENAI_API_KEY` no Oracle.

### A. borderless-api
- Subir Postgres da API (container borderless-postgres:5433) + `RATE_LIMIT_DISABLED=true pnpm dev` (3333).
- `curl -H "X-Internal-Secret: $MENTOR_INGEST_SECRET" localhost:3333/api/internal/programs/program-base/lessons | jq`
- `curl -H "X-Internal-Secret: ..." localhost:3333/api/internal/videos/<id>/media | jq` → `ffprobe -v error -show_entries format=duration -of csv=p=0 "<url>"`  (verificação AO VIVO do Panda — obrigatória)
- Criar o GitHub Actions secret MENTOR_INGEST_SECRET antes do deploy.

### B. oracle — ingestão
cd oracle-borderless
docker compose -f docker/docker-compose.yml up -d && pg_isready -h localhost -p 5432
uv run alembic upgrade head && uv run alembic current && uv run alembic check
uv run alembic downgrade 0011_navigation_persistence && uv run alembic upgrade head && uv run alembic check
docker exec oracle_borderless_db createdb -U oracle oracle_borderless_test || true
DB_NAME=oracle_borderless_test uv run alembic upgrade head && DB_NAME=oracle_borderless_test uv run alembic check
uv run pytest tests/integration/test_migration_mentor_lessons.py tests/integration/test_migration_mentor_trace.py -v
uv run pytest tests/integration/domain/lessons -v
uv run pytest tests/integration -q && uv run pytest -q
# SQL: índices de lessons/lesson_chunks (esperado ix_lesson_chunks_embedding_hnsw com hnsw + vector_cosine_ops)
uv run python cli.py mentor:ingest program-base --lesson <slug-curto> --limit 1   # depois: rodar 2x (2ª = "sem mudança")
uv run python cli.py mentor:ingest program-base                                    # fase 4 (~US$10)

### C. oracle — modo mentor
uv run pytest tests/integration/domain/lessons/test_lesson_chunk_search.py tests/integration/domain/observability/test_mentor_insights.py -v
uv run pytest tests/integration/api/test_ask_mentor_entitlement.py tests/integration/api/test_ask_mentor_real_tool.py tests/integration/api/test_lesson_status_endpoint.py tests/integration/api/test_mentor_trace_persistence.py -v
# EXPLAIN ANALYZE do search_similar filtrado por lesson_id (risco de post-filter no HNSW)
# curl -N POST /conversations/ask mode=mentor → esperar on_tool_start search_lesson + citação source_type=lesson url ?t=N; pergunta fora do assunto deve ser RESPONDIDA e gravar lesson_coverage='gap'
# curl GET /lessons/<video id>/status (ready), /lessons/fantasma/status (200 unknown), sem bearer (401)
# SELECT intent, lesson_id, lesson_coverage, retrieval_best_distance, citations_count, question_embedding IS NOT NULL FROM agent_traces ORDER BY created_at DESC LIMIT 3;
# GET /ops/mentor com e-mail da allowlist (lista o gap) e fora dela (404)
# Log do servidor: nenhum "search_lesson tool failed" nem "non-checked-in connection"

### D. platform — (lista final entra após a revisão final do D)

### D. platform (comandos exatos e checklist manual da demo em `borderless-platform/.superpowers/sdd/2026-09-11-mentor-platform/final-review.md` §"O que rodar" — resumo:)
cd borderless-platform
E2E_SKIP_PENDING_CHECKOUT=true pnpm exec playwright test e2e/tests/oracle/proxy.spec.ts e2e/tests/oracle/mentor-tab.spec.ts e2e/tests/oracle/mentor-citation.spec.ts
E2E_SKIP_PENDING_CHECKOUT=true pnpm exec playwright test e2e/tests/oracle   # nada regrediu nos 11 specs anteriores
# Demo manual: abrir uma aula do program-base desbloqueada → aba Mentor → perguntar algo da aula (citação vira link ?t=) → pergunta fora do assunto (responde mesmo assim) → aula sem transcrição (estado vazio, sem composer) → largura ~400px.
# Lacuna conhecida: o seed não tem aula Vimeo → o caminho `#t=` do Vimeo não tem cobertura e2e.

## 5. Pendências para decisão do usuário

- Confirmar em qual provider estão as aulas do Base (ativo é PANDA_VIDEO; o `getMediaUrl` do Vimeo está implementado mas NÃO verificado ao vivo).
- `evals/cases/mentor_set.json` (spec §11) não tem task em nenhum plano — criar depois que houver aula ingerida.
- Entitlement do mentor é exatamente tão forte quanto `membershipPermissions` da aula na plataforma (aula sem exigência de plano é acessível a qualquer bearer, inválido inclusive). Correto por delegação; dizer ao time.
- Follow-ups parked (sem efeito no contrato): bloco próprio no container da API; `mapPandaError`/`addLogContext`; teste do container cobrindo o ramo PANDA; wiring do WindowPicker no painel mentor do /ops; `LessonAccessDeniedError` em `support/core/exceptions`; cap de iterações do tool loop do mentor; `EXPLAIN ANALYZE` do `search_similar` (post-filter HNSW).

Ruling D9 (pós-revisão final): `status: unknown` esconde a aba Mentor (MVP só Base); spec §10 ganha a linha.

## 6. Rulings — todas as decisões tomadas em nome do usuário (copiadas dos ledgers)


## docs/superpowers/plans/2026-09-11-mentor-api.md
| T2 → T3 | T2 cria `LessonIngestService(repository, adapter)` e o controller chama `getVideoMedia`, que só nasce em T3 | **conflito**: o commit de T2 deixaria a árvore sem typecheck (o hook de commit roda biome, não tsc — passaria, mas é commit quebrado). Ver Ruling 1 |
| T1 (próprio) | `MENTOR_INGEST_SECRET: z.string().min(32)` obrigatório | **risco**: API deixa de subir em qualquer ambiente sem a var (dev, CI, produção até configurar). Ver Ruling 2 |
Ruling 1: T2 entrega SÓ a rota de aulas (schema, repo, serviço, controller com `listProgramLessons`, mock, rota, 2 casos de teste). A rota de mídia, `getVideoMedia` no controller/serviço/mock e os 2 casos de teste correspondentes passam para T3 — porque nenhum commit pode deixar a árvore sem typecheck; a spec não fixa fronteira de task — custo se errado: nenhum, estado final idêntico.
Ruling 2: `MENTOR_INGEST_SECRET` é `z.string().trim().min(32).optional()`, e o guard nega (401) quando a var está ausente — porque uma rota interna desligada por falta de config é falha visível no job de ingestão, enquanto boot quebrado derruba a API inteira; a spec (§6) exige o segredo nas rotas, não que a API dependa dele para subir — custo se errado: um ambiente mal configurado responde 401 em vez de acusar no boot, diagnóstico um passo mais longo.
Ruling 3: a variável precisa atravessar o deploy (o repo enumera env vars para produção — ver o commit "pass every NOCODB_* variable through the production deploy"); T1 inclui isso — porque um segredo que não chega ao container é o mesmo que ausente — custo se errado: nenhum.
Task 2: nota — `tsc --noEmit` do repo já tem 201 erros pré-existentes (não tocam arquivos novos); Ruling 1 continua valendo como disciplina, mas "árvore sem typecheck" não era estado limpo antes.
Ruling 4 (para T3 e adiante): em toda classe registrada no container, o nome de cada parâmetro do construtor DEVE ser igual ao nome registrado no cradle (Awilix CLASSIC) — porque é assim que a injeção resolve; e todo fix nessa área inclui um teste que resolve a cadeia pelo container real — custo se errado: nenhum.
Ruling 5: Task 3 reportou NEEDS_CONTEXT só para a verificação ao vivo do Vimeo (VIMEO_* vazios no .env; provider ativo é PANDA_VIDEO; sem DB local). Decisão: aceitar VimeoAdapter.getMediaUrl implementado pela prioridade de campos do brief (download[] → files[] hd → play.progressive[]), marcado como não-verificado em comentário e relatório, e seguir para a revisão — porque o caminho vivo do MVP é o Panda, e bloquear o plano inteiro por um provider inativo não compra nada — custo se errado: aula hospedada no Vimeo falha na ingestão com failure_reason "no media URL", visível no relatório do lote e corrigível sem tocar no resto. PENDÊNCIA PARA O USUÁRIO: confirmar em qual provider estão as aulas do Base; se Vimeo, rodar o curl do brief com token real antes da fase 4.
Ruling 6: fix wave único com findings 1,2,3,4,5,6,7. Verificação AO VIVO do Panda (curl + ffprobe) fica bloqueada pelo mesmo ambiente (sem Postgres/Docker para subir a API) — é OBRIGATÓRIA antes de rodar mentor:ingest de verdade; registrada como pendência do usuário — porque a correção é certa por inspeção (PandaVideo.video_hls tipado) e o resto do plano não depende da URL real até a fase 1 rodar de fato — custo se errado: primeira execução real do lote falha com 502 legível.
Parked (final review, minors 8-14) — Ruling 7: 8 (bloco próprio no container), 9 (estilo do controller: interface + validateParams), 10 (mapPandaError), 11 (size opcional no Vimeo — INCLUIR no fix wave, é 2 linhas e é robustez real), 12 (addLogContext), 13 (container test só cobre VIMEO), 14 (aceito por design: o segredo equivale a "baixar qualquer vídeo"; rate limit global vale para /api/internal). 8,9,10,12,13 ficam para o follow-up de merge — porque não mudam comportamento do contrato consumido pelo Oracle — custo se errado: dívida de estilo, sem efeito funcional.

## docs/superpowers/plans/2026-09-11-mentor-ingestao-oracle.md
| T7 (próprio) | `--lesson X --force`: busca em `list_pending(program, max_attempts=10**6)` | **defeito do plano**: `list_pending` filtra status ∈ {pending, failed}; aula READY nunca aparece, então `--force` numa aula pronta não acha nada. Ver Ruling B1 |
Ruling B1: o comando seleciona o alvo de `--lesson` a partir da lista devolvida por `SyncProgramLessonsAction.execute()` (que traz TODAS as aulas do programa, qualquer status), filtrando por `video_slug`; sem `--force`, ainda exige status ∈ {pending, failed} e `attempts < MENTOR_MAX_ATTEMPTS`; com `--force`, aceita qualquer status. Remove o hack `max_attempts=10**6` — porque `--force` existe justamente para re-embedar aula READY, e a spec §7 diz "`--force`" sem restringir status — custo se errado: nenhum, é o comportamento óbvio da flag.
Ruling B2: seguir com as tasks cujo teste é unitário; migrations e testes de integração são ESCRITOS e validados offline (history/compile/import), NÃO executados, com isso dito explicitamente no relatório de cada task; o controller executa `alembic upgrade head`, `alembic check` e `pytest tests/integration` assim que houver banco, antes de fechar o plano — porque parar o plano inteiro por um serviço parado no host não compra nada e o trabalho é integralmente revisável por leitura — custo se errado: migration com erro só aparece na primeira execução; mitigado pela leitura cuidadosa do revisor e pela re-execução obrigatória antes do fechamento.
Task 1: complete (commits 017a19e..6322263, review clean after 1 fix round; migration NÃO executada — pendente de banco, ver Ruling B2)
Ruling B3: a spec (§4: "blocos de até MENTOR_CHUNK_SIZE") manda: teto duro, `<=` estrito, SEM tolerância. O defeito é do teste do plano, não do algoritmo. Teste substituído no plano por dois casos (15+1+4=20 cabe; 15+1+5=21 quebra) — commit docs no repo. Custo se errado: nenhum funcional; um chunk nunca passa de 800 chars, que é o contrato que o embedding e a citação temporal assumem.
Ruling B4: revisor tem razão; `save()` levanta `NotFoundError` — porque um erro fora da hierarquia vira 500 mudo quando o repositório for chamado de rota/CLI; plano corrigido (commit docs) — custo se errado: nenhum.
Task 3: complete (commits 1024a3f..8ed2640, review clean after 1 fix round; integração ESCRITA, não executada — Ruling B2)
Task 5: nota — ffmpeg/ffprobe ausentes e sem sudo; Step 5 do brief (verificação real do binário) NÃO executável aqui; Dockerfile deve ganhar o pacote mesmo assim (Ruling B2 se aplica).
Ruling B5: o save do caminho de falha ganha try/except próprio (loga e segue; execute devolve o IngestResult FAILED mesmo assim) — porque "execute nunca levanta" é o contrato que protege o lote, e a spec §7 exige que uma aula ruim não derrube as outras — custo se errado: nenhum.
Ruling B6: recuperação de claim obsoleto — setting `MENTOR_CLAIM_STALE_MINUTES=120`; `list_pending` passa a incluir também aulas em `transcribing` cujo `updated_at` < now - stale (além de pending/failed abaixo do teto). Menor mudança que fecha o buraco sem reaper/cron; a spec §7 ganha uma frase — porque um lote interrompido por OOM/restart não pode exigir intervenção manual no banco — custo se errado: uma transcrição legítima mais longa que 120 min poderia ser re-claimada por execução concorrente (improvável: aula de 1h transcreve em minutos); mitigável subindo o setting.
Ruling B7: o claim é commitado DENTRO da action logo após o save (sessão via CurrentAsyncSessionContext.get().commit()), e o save do claim entra no bloco protegido (falha → IngestResult FAILED sem levantar). O comando mantém o commit por aula — porque a spec §7 passo 1 exige "commit imediato" e o plano o omitiu — custo se errado: nenhum; é o desenho da spec.
Ruling B8 (fix wave): entram 1,2,3,4,5,6 + minors 7 (uuid7), 8 (--limit 0), 9 (errors="replace"), 10 (ffprobe N/A), 16 (robustez dos testes de integração), 18 (validar esquema http(s) da URL). Parked com ruling: 11 (skip só com chunks>0 — defensivo; §10 trata no tool), 12 (hash-skip raro — nota, não defeito), 13 (video_slug repetido entre módulos — imprimir nota, follow-up), 14 (--force sem --lesson não reprocessa ready — leitura defensável de B1; documentar), 15 (bloco de MENTOR_* no .env.example — follow-up), 17 (can_retry não usado — deixar), 19 (barrel — convenção) — custo se errado: dívida menor, sem efeito no contrato.

## docs/superpowers/plans/2026-09-11-mentor-modo-oracle.md
Ambiente: sem Postgres (Docker Desktop parado), sem ffmpeg. Ruling B2 (integração escrita, não executada) continua valendo aqui.
| T3/T4 (próprio) | plano manda "passar lesson_id para o state na chamada de run()", mas `TurnGraphPort.run()`/runner não têm esse parâmetro | **lacuna do plano**: exige alterar `run()` (port + runner + tests/fakes/fake_turn_graph.py). Ver Ruling C1 |
| T5 (próprio) | migration 0013 usa `Vector(settings.EMBEDDING_DIM)` | mesma lição da B-T1: congelar `EMBEDDING_DIM = 1536` na migration. Ver Ruling C2 |
Ruling C1: T3 acrescenta `lesson_id: str | None = None` a `TurnGraphPort.run()` e ao runner (`_initial_state`/equivalente escreve `state["lesson_id"]` quando presente), atualiza `tests/fakes/fake_turn_graph.py` e chamadores; T4 passa `lesson_id=str(lesson.platform_video_id)`… CORREÇÃO: o state carrega o id da PLATAFORMA (string) para o prompt/trace, e o `configurable["lesson_id"]` carrega o UUID interno para a tool — porque o modelo/trace falam em id de vídeo da plataforma e a busca vetorial usa a PK — custo se errado: nenhum funcional; nomes explícitos evitam confundir os dois ids.
Ruling C2: migration 0013 congela `EMBEDDING_DIM = 1536` (snapshot), como a 0001 e a 0012 corrigida — mesmo motivo (determinismo do histórico) — custo se errado: nenhum.
Ruling C3: search_similar acrescenta `LessonChunkModel.embedding.is_not(None)` ao WHERE — porque a coluna é nullable e cosine_distance com NULL devolve NULL/ordena estranho — custo se errado: nenhum.
Task 1: complete (commits ea2ca90..2e38faa, review clean; integração ESCRITA, não executada — Ruling B2)
Ruling C4a: corrigir o FakeAction do teste para definir `self.last_query_embedding = [0.1, 0.2]` em execute (espelha o contrato real da Action); a tool continua lendo o atributo diretamente — porque um getattr com default esconderia regressão real — custo se errado: nenhum.
Ruling C4b: separar "tools que o ToolNode EXECUTA" de "tools que o modelo ENXERGA". `tool_node_tools()` passa a incluir search_lesson (o ToolNode precisa executá-la); o conjunto vinculado ao modelo em `_answer_model` NÃO muda nesta task (exclui search_lesson) — a Task 3, que já vai passar `mode` para o nó de resposta, vincula `build_mentor_tools()` (e só ele) quando mode == "mentor". Teste existente de R12 continua verde — porque a spec §2.1/§5 quer a tool disponível só ao mentor — custo se errado: nenhum; T3 fecha o circuito.
Ruling C5 (contrato para T4/T5): extra_config do turno mentor inclui `"question_embedding": []` além de `"lesson_distances": []`; T5 lê `emb = cfg.get("question_embedding") or None` (lista vazia → None) — porque é a única forma de a tool devolver dado ao trace atravessando a cópia rasa — custo se errado: nenhum.
Task 5: complete (commits 3234b3a..c0e9e45, review clean; migration 0013 e integração ESCRITAS, não executadas — Ruling B2)
Task 6: complete (commits c0e9e45..a664847, review clean; integração ESCRITA, não executada — Ruling B2)
Ruling C6 (C1): a tool `search_lesson` abre o próprio `async_session_scope()` em volta de `action.execute(...)` (src/support/agent/ não é src/domain/, o teste de fronteira continua verde); ADR-0020 ganha uma frase: "tool que precisa de banco durante o stream abre escopo próprio e curto"; teste de integração ESCRITO que roda a tool real dentro de um turno e afirma citação lesson em captured["citations"] — porque é a menor mudança correta e mantém domínio/grafo sem conhecer o fio — custo se errado: nenhum funcional; uma sessão curta a mais por busca.
Ruling C7 (I2): MENTOR_ENABLED vira kill switch de verdade: com False, POST /conversations/ask com mode=mentor → 404 "mentor desabilitado" antes de qualquer trabalho, e GET /lessons/{id}/status → 404 — porque a spec lista o setting e um flag que não faz nada engana a operação — custo se errado: precisa setar MENTOR_ENABLED=true no .env do Oracle para a demo (documentar).
Ruling C8 (fix wave): entram C1, I1, I2, I3, I4 + T4 docstring, T5 teste de ordem do fill, T3 enable_tools=False+mentor, M1 (403 opaco), M2 (retrieval_top_k), M4 (days 1..365), M7 (dedupe citações por url), M8 (quote nos slugs da URL). Parked: M3 (janela do /ops — copy "últimos 30 dias" entra, wiring do WindowPicker fica), M5 (exceção no módulo da action), M6 (estilo), M9 (cap de iterações — follow-up), M10 (EXPLAIN ANALYZE na lista pós-DB). Spec: evals/cases/mentor_set.json é lacuna do PLANO — follow-up após banco (precisa de aula ingerida para casos reais); entitlement ungated = comportamento correto da plataforma, dizer ao time.

## docs/superpowers/plans/2026-09-11-mentor-platform.md
Ambiente: e2e exige container borderless-postgres (5433) + API (3333) + app (3000) — Docker Desktop parado. Ruling D3 abaixo.
| T2 (próprio) | regex `LESSON_PATH` com `[a-z0-9-]+` por segmento | **risco**: slug com maiúscula/underscore não viraria link. Ver Ruling D1 |
| T2 (próprio) | "use o Link do repo (wrapper do next-intl se houver)" | componentes de app usam `next/link` direto. Ver Ruling D2 |
| T4 (próprio) | fixtures e2e `aula-sem-transcricao`/`aula-bloqueada` precisam existir no mock de programas | a confirmar pelo implementador (o mock é semeado no banco via `pnpm db:mock`, não em arquivo) — ver Ruling D3 |
Ruling D1: `LESSON_PATH` usa `[\w-]+` por segmento (`^\/programs\/[\w-]+\/[\w-]+\/[\w-]+\?t=\d+$`) — porque slugs de programa/módulo/vídeo são strings livres no Prisma e a guarda precisa barrar travessia/`//host`/query extra, não caixa de letra — custo se errado: nenhum de segurança (`\w` não casa `/`, `.`, `?`, `:`), só um slug exótico continuaria sem link.
Ruling D2: usar `next/link` direto, como os componentes irmãos da página de programas — porque é o padrão do repo nessa área e o `[locale]` já está no path relativo devolvido pelo Oracle? NÃO: a URL do Oracle é `/programs/...` sem locale. Verificar como os links irmãos (module-card.tsx) montam href sem locale — se `next/link` com path sem locale já funciona neles (middleware do next-intl reescreve), seguir igual; se eles prefixam locale, prefixar também — custo se errado: link cai na locale default, não quebra.
Ruling D3: Playwright do plano D é ESCRITO e validado por `tsc`/lint, NÃO executado, até o Docker subir (mesma lógica do Ruling B2 do Oracle); T1-T3 são verificáveis por `tsc --noEmit` — custo se errado: regressão de UI só aparece na primeira execução real; mitigado pela leitura do revisor e pela execução obrigatória antes do fechamento do plano.
Ruling D2 (resolvido): `next/link` com o path cru `/programs/<p>/<m>/<v>?t=N` — `routing.localePrefix = "never"` e module-card.tsx monta `videoLink` exatamente assim; a citação do Oracle já vem nesse formato — custo se errado: nenhum.
Ruling D4: iniciar a Task 1 do plano D enquanto a revisão final do plano C (só leitura, outro repo) roda — porque as 7 tasks do C estão fechadas e revisadas e a T1 do D é código de contrato já fixado pela spec (mode/lesson_id no ask; GET /lessons/<uuid>/status; citação relativa) — custo se errado: se a revisão final do C alterar um contrato, retrabalho pequeno e localizado na T1/T4 do D.
Task 1: complete (commits 329ce90e..604505b5, review clean; e2e ESCRITO, não executado — Ruling D3)
Task 2: complete (commits 604505b5..a9e7961d, review clean after 1 fix round; e2e ESCRITO, não executado — Ruling D3)
Ruling D5: useLessonStatus declara `OracleRequestError` — porque é o que o serviço lança e o que os irmãos declaram; o brief errou — custo se errado: nenhum.
Ruling D6: o efeito-espelho também roda em `status === "error"` e limpa `pending` (mantendo o conteúdo parcial) — porque bolha "pensando" eterna ao lado do painel de erro é bug de UI; o brief só previu `done` — custo se errado: nenhum.
Ruling D7: erro na query de prontidão renderiza o copy "indisponível" (não "preparando"); chave `retry` sem uso é removida dos dois locales (paridade mantida) — porque dizer "volte em breve" para um 401 engana o aluno — custo se errado: nenhum.
Ruling D8: as specs e2e do mentor compartilham constantes de slugs reais exportadas de um único lugar (fixture), e a spec da T2 é repontada nesta task — porque é a única cobertura do fluxo de citação e o slug do brief era inventado — custo se errado: nenhum.
