"""Integration and unit tests for the Canis application (Auth, Catalog, Finance)."""

import os
from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Force in-memory SQLite database before importing application modules
os.environ["TESTING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["GOOGLE_CLIENT_ID"] = ""
os.environ["GOOGLE_CLIENT_SECRET"] = ""

from setrem_estagio_canis.api.web import calculate_metrics, get_priority_alerts
from setrem_estagio_canis.core.security import create_access_token
from setrem_estagio_canis.database.models import Base
from setrem_estagio_canis.database.repository import (
    get_user_by_email,
    list_animals,
    list_stock,
    seed_initial_data,
)
from setrem_estagio_canis.database.session import SessionLocal, engine
from setrem_estagio_canis.main import app


@pytest.fixture(autouse=True)
def reset_database() -> Generator[None, None, None]:
    """Recreate in-memory schema and seed fresh data before each test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_initial_data(db)
    yield


def _authenticated_client(
    email: str = "coordenacao@patasepelos.org.br",
    password: str = "prototipo2026",
) -> TestClient:
    """Create a TestClient authenticated via the local login endpoint."""
    test_client = TestClient(app)
    resp = test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "access_token" in test_client.cookies
    return test_client


def test_calculate_metrics_and_alerts() -> None:
    """Ensure dashboard metrics and priority alerts are computed from DB records."""
    with SessionLocal() as db:
        animals = list_animals(db)
        stock = list_stock(db)

    metrics = calculate_metrics(animals, stock)
    alerts = get_priority_alerts(animals, stock)

    assert metrics["total_animals"] == len(animals)
    assert metrics["dogs_count"] >= 1
    assert metrics["cats_count"] >= 1
    assert metrics["critical_stock_count"] >= 1
    assert metrics["adoptions_count"] >= 1
    assert {"Estoque", "Validade", "Clinica"}.issubset({a.category for a in alerts})


def test_unauthenticated_root_redirects_to_login() -> None:
    """Ensure accessing / without a JWT cookie redirects to /login."""
    anon = TestClient(app)
    resp = anon.get("/", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_authenticated_login_redirects_to_root() -> None:
    """Ensure accessing /login while authenticated redirects to /."""
    client = _authenticated_client()
    resp = client.get("/login", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_logout_clears_cookie_and_redirects() -> None:
    """Ensure /auth/logout clears the JWT cookie and redirects to /login."""
    client = _authenticated_client()
    resp = client.get("/auth/logout", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
    after = client.get("/", follow_redirects=False)
    assert after.status_code == 303
    assert after.headers["location"] == "/login"


def test_google_oauth_new_user_pending_then_admin_approves() -> None:
    """New Google users start as pending until approved by an admin."""
    anon = TestClient(app)
    state_nonce = "test-csrf-nonce-123"
    state_jwt = create_access_token({"oauth_state": state_nonce})
    anon.cookies.set("oauth_state", state_jwt)

    fake_profile = {
        "sub": "google-sub-novo-001",
        "email": "novo.voluntario@gmail.com",
        "email_verified": True,
        "name": "Joao Novo",
        "picture": "https://example.com/avatar.png",
    }

    with patch(
        "setrem_estagio_canis.api.auth._exchange_google_code_for_profile",
        return_value=fake_profile,
    ):
        cb_resp = anon.get(
            f"/auth/google/callback?code=abc&state={state_nonce}",
            follow_redirects=False,
        )

    assert cb_resp.status_code == 303
    assert cb_resp.headers["location"] == "/aguardando-aprovacao"

    # Pending user cannot access dashboard yet
    dash_attempt = anon.get("/", follow_redirects=False)
    assert dash_attempt.status_code == 303
    assert dash_attempt.headers["location"] == "/aguardando-aprovacao"

    # Admin approves the pending user
    with SessionLocal() as db:
        pending_user = get_user_by_email(db, "novo.voluntario@gmail.com")
        assert pending_user is not None
        assert pending_user.role == "pendente"
        pending_id = pending_user.id

    admin_client = _authenticated_client()
    approve_resp = admin_client.post(
        f"/admin/usuarios/{pending_id}/papel",
        data={"role": "voluntario"},
        follow_redirects=False,
    )
    assert approve_resp.status_code == 303

    # Now the previously pending user can access the dashboard
    dash_ok = anon.get("/")
    assert dash_ok.status_code == 200
    assert "Visao Geral" in dash_ok.text


def test_public_adoption_catalog_without_login() -> None:
    """Public adoption catalog works without authentication and filters properly."""
    anon = TestClient(app)

    resp = anon.get("/adocao")
    assert resp.status_code == 200
    assert "Catalogo Publico de Adocao" in resp.text
    assert "Barao" in resp.text
    assert "Amora" in resp.text
    assert "Pipoca" not in resp.text

    resp_cats = anon.get("/adocao/busca?especie=Felina")
    assert resp_cats.status_code == 200
    assert "Amora" in resp_cats.text
    assert "Barao" not in resp_cats.text


def test_dashboard_and_navigation_pages() -> None:
    """Authenticated volunteer/admin can access all core operational screens."""
    client = _authenticated_client()

    for path, heading in [
        ("/", "Indicadores Operacionais"),
        ("/animais", "Gestao de Animais"),
        ("/prontuarios", "Prontuarios Clinicos"),
        ("/estoque", "Controle de Estoque e Insumos"),
        ("/lares", "Lares Temporarios e Adocoes"),
        ("/financeiro", "Financeiro e Prestacao de Contas"),
        ("/admin/usuarios", "Usuarios e Permissoes"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert heading in response.text


def test_animals_search_create_and_clinical_record() -> None:
    """Test animal filtering, creation, clinical record tabs, and new events."""
    client = _authenticated_client()

    # Search by name
    resp_search = client.get("/animais/busca?termo=Pipoca")
    assert resp_search.status_code == 200
    assert "Pipoca" in resp_search.text
    assert "Thor" not in resp_search.text

    # Not found message
    resp_empty = client.get("/animais/busca?termo=InexistenteXYZ")
    assert resp_empty.status_code == 200
    assert "Nenhum animal encontrado" in resp_empty.text

    # Create new rescue persisted in DB
    create_resp = client.post(
        "/animais",
        data={
            "name": "Caramelo",
            "species": "Canina",
            "size": "Medio",
            "location": "Canil Central",
            "rescue_notes": "Resgatado no centro.",
        },
        follow_redirects=False,
    )
    assert create_resp.status_code == 303
    assert "Caramelo" in client.get("/animais").text

    # Clinical record & tabs
    rec_resp = client.get("/animais/1/prontuario")
    assert rec_resp.status_code == 200
    assert "Prontuario Clinico: Pipoca" in rec_resp.text
    assert "Vacina V10" in rec_resp.text

    tab_vac = client.get("/animais/1/prontuario/aba/vacinas")
    assert tab_vac.status_code == 200
    assert "Carteira de Vacinas e Vermifugos" in tab_vac.text

    # Add clinical event via HTMX POST
    ev_resp = client.post(
        "/animais/1/atendimentos",
        data={
            "title": "Curativo ortopedico",
            "veterinarian": "Dra. Camila",
            "notes": "Boa evolucao.",
        },
    )
    assert ev_resp.status_code == 200
    assert "Curativo ortopedico" in ev_resp.text


def test_stock_search_and_movement() -> None:
    """Test stock filtering and real quantity updates in DB."""
    client = _authenticated_client()

    resp_vac = client.get("/estoque/busca?categoria=Vacina")
    assert resp_vac.status_code == 200
    assert "Nobivac" in resp_vac.text
    assert "Simparic" not in resp_vac.text

    move_resp = client.post(
        "/estoque/movimentacao",
        data={"item_id": "2", "movement_type": "Entrada", "quantity": "10"},
        follow_redirects=False,
    )
    assert move_resp.status_code == 303
    assert "13 frascos" in client.get("/estoque").text


def test_financial_module_create_pay_and_csv() -> None:
    """Test creating financial entries, marking pending as paid, and CSV export."""
    client = _authenticated_client()

    create_resp = client.post(
        "/financeiro/lancamentos",
        data={
            "tx_type": "Entrada",
            "category": "Doacao PIX",
            "description": "Doacao comunitaria teste",
            "amount": "350,50",
            "payment_method": "PIX",
            "status": "Pago",
            "related_animal": "",
        },
        follow_redirects=False,
    )
    assert create_resp.status_code == 303
    fin_page = client.get("/financeiro")
    assert "Doacao comunitaria teste" in fin_page.text
    assert "R$ 350,50" in fin_page.text

    csv_resp = client.get("/financeiro/exportar-csv")
    assert csv_resp.status_code == 200
    assert "Doacao comunitaria teste" in csv_resp.text


def test_adoption_term_and_static_logo() -> None:
    """Test printable adoption term and static logo serving."""
    client = _authenticated_client()

    term_resp = client.get("/termo-adocao/1")
    assert term_resp.status_code == 200
    assert "Termo de Responsabilidade" in term_resp.text
    assert "Pipoca" in term_resp.text

    assert client.get("/termo-adocao/9999").status_code == 404

    logo_resp = client.get("/static/logo.jpg")
    assert logo_resp.status_code == 200
    assert logo_resp.headers["content-type"] in ["image/jpeg", "image/jpg"]

    svg_logo = client.get("/static/laika-logo.svg")
    assert svg_logo.status_code == 200
    assert "image/svg+xml" in svg_logo.headers["content-type"]

    favicon = client.get("/static/favicon.svg")
    assert favicon.status_code == 200
    assert "image/svg+xml" in favicon.headers["content-type"]


def test_user_profile_settings_and_avatar_upload() -> None:
    """Test updating display name, theme preference, and profile avatar."""
    client = _authenticated_client()

    settings_page = client.get("/configuracoes")
    assert settings_page.status_code == 200
    assert "Configuracoes da Conta" in settings_page.text

    fake_png = b"\x89PNG\r\n\x1a\nfake-avatar-bytes"
    update_resp = client.post(
        "/auth/perfil",
        data={"nome": "Thales Coordenacao", "tema": "light"},
        files={"foto": ("avatar.png", fake_png, "image/png")},
        follow_redirects=False,
    )
    assert update_resp.status_code == 303

    updated_page = client.get("/configuracoes")
    assert "Thales Coordenacao" in updated_page.text
    assert 'class="light"' in updated_page.text

    avatar_resp = client.get("/auth/avatar")
    assert avatar_resp.status_code == 200
    assert avatar_resp.content == fake_png
