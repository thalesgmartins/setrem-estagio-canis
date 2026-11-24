"""Integration and unit tests for the Laika application."""

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
    list_financial_transactions,
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
        transactions = list_financial_transactions(db)

    metrics = calculate_metrics(animals, stock)
    alerts = get_priority_alerts(stock, transactions)

    assert metrics["total_animals"] == len(animals)
    assert metrics["available_count"] >= 1
    assert metrics["critical_stock_count"] >= 1
    assert {"Estoque", "Financeiro"}.issubset({a.category for a in alerts})


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

    dash_ok = anon.get("/")
    assert dash_ok.status_code == 200
    assert "Visao Geral" in dash_ok.text


def test_public_adoption_catalog_without_login() -> None:
    """Public adoption catalog works without login and hides volunteer link."""
    anon = TestClient(app)

    resp = anon.get("/adocao")
    assert resp.status_code == 200
    assert "Catalogo Publico de Adocao" in resp.text
    assert "Area do Voluntario" not in resp.text
    assert "Barao" in resp.text
    assert "Amora" in resp.text
    assert "Pipoca" not in resp.text

    resp_cats = anon.get("/adocao/busca?especie=Felina")
    assert resp_cats.status_code == 200
    assert "Amora" in resp_cats.text
    assert "Barao" not in resp_cats.text


def test_animal_create_edit_foster_transfer_and_vet_note() -> None:
    """Test creating, editing, transferring foster home, and logging vet care."""
    client = _authenticated_client()

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

    # Open dedicated edit page and transfer animal to a foster home
    edit_page = client.get("/animais/1")
    assert edit_page.status_code == 200
    assert "Pipoca" in edit_page.text

    save_resp = client.post(
        "/animais/1/editar",
        data={
            "name": "Pipoca",
            "species": "Canina",
            "breed": "SRD",
            "size": "Medio (14 kg)",
            "age_approx": "2 anos",
            "gender": "Femea",
            "status": "Lar Temporario",
            "location": "Lar Temporario - Mariana Weber (Bela Uniao)",
            "temperament": "Muito carinhosa",
            "rescue_notes": "Recuperada da cirurgia.",
            "neutered": "on",
        },
        follow_redirects=False,
    )
    assert save_resp.status_code == 303
    updated_page = client.get("/animais/1")
    assert "Mariana Weber" in updated_page.text

    # Add veterinary care visit note
    vet_resp = client.post(
        "/animais/1/atendimentos",
        data={
            "title": "Retorno clinica parceira",
            "veterinarian": "Dra. Camila",
            "notes": "Alta liberada.",
        },
        follow_redirects=False,
    )
    assert vet_resp.status_code == 303
    assert "Retorno clinica parceira" in client.get("/animais/1").text


def test_foster_home_crud_and_adoption_registration() -> None:
    """Test creating/editing foster homes and registering a completed adoption."""
    client = _authenticated_client()

    # Create foster home
    resp_create = client.post(
        "/lares",
        data={
            "volunteer_name": "Fernanda Costa",
            "contact": "(55) 99800-1122",
            "neighborhood": "Industrial",
            "capacity": "2",
        },
        follow_redirects=False,
    )
    assert resp_create.status_code == 303
    assert "Fernanda Costa" in client.get("/lares").text

    # Register adoption (marks animal as Adopted automatically)
    resp_adopt = client.post(
        "/adocoes",
        data={
            "animal_id": "4",
            "adopter_name": "Marcos Pereira",
            "adopter_cpf": "111.222.333-44",
            "adopter_contact": "(55) 99777-8899",
            "adopter_address": "Rua das Flores, 120",
        },
        follow_redirects=False,
    )
    assert resp_adopt.status_code == 303
    assert "Marcos Pereira" in client.get("/lares").text
    assert "Adotado" in client.get("/animais/4").text


def test_stock_supplies_create_filter_and_movement() -> None:
    """Test supplies stock filtering, new item creation, and quantity update."""
    client = _authenticated_client()

    resp_racao = client.get("/estoque/busca?categoria=Racao")
    assert resp_racao.status_code == 200
    assert "Racao Seca Caes Adultos" in resp_racao.text
    assert "Areia Sanitaria" not in resp_racao.text

    create_resp = client.post(
        "/estoque/itens",
        data={
            "name": "Shampoo Neutro 5L",
            "category": "Higiene",
            "quantity": "4",
            "unit": "galoes",
            "min_quantity": "2",
        },
        follow_redirects=False,
    )
    assert create_resp.status_code == 303
    assert "Shampoo Neutro 5L" in client.get("/estoque").text

    move_resp = client.post(
        "/estoque/movimentacao",
        data={"item_id": "2", "movement_type": "Entrada", "quantity": "5"},
        follow_redirects=False,
    )
    assert move_resp.status_code == 303
    assert "7 sacos" in client.get("/estoque").text


def test_financial_module_and_csv() -> None:
    """Test creating financial entries and exporting CSV accountability report."""
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
    assert "Doacao comunitaria teste" in client.get("/financeiro").text

    csv_resp = client.get("/financeiro/exportar-csv")
    assert csv_resp.status_code == 200
    assert "Doacao comunitaria teste" in csv_resp.text


def test_user_profile_settings_and_local_assets() -> None:
    """Test personal settings, avatar upload, and local static assets."""
    client = _authenticated_client()

    fake_png = b"\x89PNG\r\n\x1a\nfake-avatar-bytes"
    update_resp = client.post(
        "/auth/perfil",
        data={"nome": "Thales Coordenacao", "tema": "light"},
        files={"foto": ("avatar.png", fake_png, "image/png")},
        follow_redirects=False,
    )
    assert update_resp.status_code == 303
    assert 'class="light"' in client.get("/configuracoes").text
    assert client.get("/auth/avatar").content == fake_png

    for asset_path in [
        "/static/laika-logo.svg",
        "/static/favicon.svg",
        "/static/css/materialdesignicons.min.css",
        "/static/js/htmx.min.js",
    ]:
        assert client.get(asset_path).status_code == 200
