# Laika — Gestao Operacional (ONG Patas e Pelos)

Sistema web integrado para gestao de animais acolhidos, lares temporarios, adocoes, estoque de suprimentos (racao, higiene e acessorios), controle financeiro e catalogo publico de adocao da ONG Patas e Pelos.

## Arquitetura e Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic
- **Banco de Dados**: PostgreSQL 16 (producao/Docker) ou SQLite (desenvolvimento local)
- **Autenticacao**: JWT em cookie HTTP-only + Google OAuth 2.0 (com aprovacao de usuarios por administrador)
- **Frontend**: Jinja2 + HTMX + Tailwind CSS + Material Design Icons (**100% locais em `static/`, sem CDN**)
- **Conteinerizacao**: Docker + Docker Compose

### Modulos Principais

- **`/` (Visao Geral)**: KPIs operacionais (animais acolhidos, disponiveis p/ adocao, em lar temporario e saldo em caixa) e alertas de estoque baixo e contas pendentes.
- **`/animais` e `/animais/{id}`**: cadastro, busca/filtro HTMX, edicao completa (incluindo transferencia de lar temporario), historico de consultas em clinicas parceiras e emissao de termo de adocao (`/termo-adocao/{id}`).
- **`/lares`**: cadastro, edicao e exclusao de lares temporarios voluntarios + registro de adocoes concluidas.
- **`/estoque`**: controle de racao, higiene e acessorios com cadastro de itens, movimentacoes e ajuste rapido (`-1` / `+1`).
- **`/financeiro`**: controle de entradas (doacoes PIX, rifas, apadrinhamentos) e saidas (clinicas parceiras, racao, castracoes), marcacao de contas pagas e exportacao CSV (`/financeiro/exportar-csv`).
- **`/adocao` (Publico — sem login)**: catalogo publico exibindo apenas animais com status `Disponivel para Adocao`, com filtros HTMX e contato via WhatsApp.
- **`/admin/usuarios` (Somente Admin)**: aprovacao de contas Google pendentes, pre-cadastro de e-mails autorizados e ativacao/desativacao de usuarios.
- **`/configuracoes`**: alteracao de nome, foto de perfil (salva em `UPLOAD_DIR/avatars/`) e tema (`Escuro` / `Claro`).

---

## Configuracao do Ambiente (`.env`)

Copie o arquivo de exemplo:

```bash
cp .env.example .env
```

Principais variaveis:

| Variavel | Descricao |
| :--- | :--- |
| `DATABASE_URL` | String SQLAlchemy (`postgresql+psycopg://postgres:postgres@postgres:5432/laika` no Docker ou `sqlite:///./laika.db` local) |
| `SECRET_KEY` | Chave secreta usada para assinar tokens JWT |
| `UPLOAD_DIR` | Diretorio de uploads/avatares (`/tmp/uploads/laika` — montado no volume `laika_uploads` no Docker) |
| `ADMIN_EMAILS` | Lista de e-mails (separados por virgula) que entram automaticamente como `admin` no login Google |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Credenciais OAuth 2.0 do Google Cloud |
| `GOOGLE_REDIRECT_URI` | URL de callback (`http://localhost:8000/auth/google/callback`) |
| `ONG_WHATSAPP` | Telefone WhatsApp usado no catalogo publico `/adocao` |
| `SEED_DEMO_DATA` | `false` (padrao — banco 100% limpo) ou `true` para popular com dados de exemplo |

---

## Execucao com Docker (Recomendado)

```bash
cp .env.example .env
cp docker-compose.yml.example docker-compose.yml
cp docker-compose.override.yml.example docker-compose.override.yml

# No .env, aponte DATABASE_URL para o servico postgres:
# DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres:5432/laika

docker compose up --build
```

### Resetar para um banco 100% em branco

Com `SEED_DEMO_DATA=false` no `.env`:

```bash
# Se estiver usando Docker + PostgreSQL (apaga o volume do banco e recria limpo):
docker compose down -v
docker compose up -d --build

# Se estiver rodando localmente com SQLite:
rm -f laika.db
```

As migracoes do Alembic sao aplicadas automaticamente na inicializacao da aplicacao (`alembic upgrade head`).

---

## Execucao Local (sem Docker)

```bash
uv sync
uv run uvicorn setrem_estagio_canis.main:app --reload --port 8000
```

Acesse:
- Painel interno: `http://localhost:8000`
- Catalogo publico de adocao: `http://localhost:8000/adocao`

---

## Build Local de Assets (Tailwind CSS, HTMX e MDI)

Os assets estaticos ficam versionados em `setrem_estagio_canis/static/`:
- `static/css/tailwind.min.css` (gerado localmente)
- `static/css/materialdesignicons.min.css` + `static/fonts/materialdesignicons-webfont.woff2`
- `static/js/htmx.min.js`
- `static/laika-logo.svg` e `static/favicon.svg`

Sempre que adicionar novas classes Tailwind nos templates HTML, recompile o CSS local com:

```bash
npx tailwindcss@3 -i ./setrem_estagio_canis/static/css/input.css -o ./setrem_estagio_canis/static/css/tailwind.min.css --minify
```

---

## Testes e Qualidade de Codigo

```bash
uv run pytest
uv run mypy setrem_estagio_canis tests
uv run ruff check setrem_estagio_canis tests
uv run ruff format --check setrem_estagio_canis tests
```
