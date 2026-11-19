# Canis - Sistema de Gestao Operacional

Sistema web integrado para centralizacao de resgates, prontuarios clinicos, controle de estoque de medicamentos e administracao de lares temporarios e adocoes na ONG Patas e Pelos (Horizontina/RS).

## Execucao do Prototipo Interativo

Para iniciar o servidor de desenvolvimento com recarregamento automatico:

```bash
uv run uvicorn setrem_estagio_canis.main:app --reload --port 8000
```

Acesse no navegador: `http://localhost:8000`

## Execucao dos Testes e Qualidade

```bash
# Executar suíte de testes
uv run pytest

# Verificacao de tipos estaticos
uv run mypy setrem_estagio_canis tests

# Formatacao e linter
uv run ruff check setrem_estagio_canis tests
uv run ruff format --check setrem_estagio_canis tests
```
