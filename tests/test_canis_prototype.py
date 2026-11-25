"""Integration and unit tests for the Laika application."""

import io
import os
from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

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
    list_adoptions,
    list_animals,
    list_financial_transactions,
    list_stock,
    seed_initial_data,
)
from setrem_estagio_canis.database.session import SessionLocal, engine
from setrem_estagio_canis.main import app


def _make_test_image(width: int = 1600, height: int = 1200) -> bytes:
    """Create a valid in-memory PNG image for upload and downscaling tests."""
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color=(5, 172, 120))
    img.save(buf, format="PNG")
    return buf.getvalue()


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
    assert "Visão Geral" in dash_ok.text


def test_public_adoption_catalog_without_login() -> None:
    """Public adoption catalog works without login and hides volunteer link."""
    anon = TestClient(app)

    resp = anon.get("/adocao")
    assert resp.status_code == 200
    assert "Catálogo Público de Adoção" in resp.text
    assert "Area do Voluntario" not in resp.text
    assert "Barao" in resp.text
    assert "Amora" in resp.text
    assert "Pipoca" not in resp.text

    resp_cats = anon.get("/adocao/busca?especie=Felina")
    assert resp_cats.status_code == 200
    assert "Amora" in resp_cats.text
    assert "Barao" not in resp_cats.text

    # Public detail modal works without login
    detail_resp = anon.get("/adocao/6")
    assert detail_resp.status_code == 200
    assert "Amora" in detail_resp.text


def test_animal_create_edit_foster_transfer_and_vet_note() -> None:
    """Test creating, editing, transferring foster home, and logging vet care."""
    client = _authenticated_client()

    create_resp = client.post(
        "/animais",
        data={
            "name": "Caramelo",
            "species": "Canina",
            "size": "Médio",
            "location": "Lucia Schmidt (Centro)",
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
            "breed": "Sem Raça Definida",
            "size": "Médio",
            "age_approx": "2 anos",
            "gender": "Fêmea",
            "status": "Lar Temporário",
            "location": "Mariana Weber (Bela Uniao)",
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
            "title": "Retorno clínica parceira",
            "veterinarian": "Dra. Camila",
            "notes": "Alta liberada.",
        },
        follow_redirects=False,
    )
    assert vet_resp.status_code == 303
    assert "Retorno clínica parceira" in client.get("/animais/1").text


def test_animal_photos_downscale_primary_and_gallery() -> None:
    """Test uploading animal photos, WebP downscaling, primary switch, and deletion."""
    client = _authenticated_client()
    large_png = _make_test_image(1600, 1200)

    upload_resp = client.post(
        "/animais/6/fotos",
        files=[
            ("fotos", ("foto1.png", large_png, "image/png")),
            ("fotos", ("foto2.png", large_png, "image/png")),
        ],
        follow_redirects=False,
    )
    assert upload_resp.status_code == 303

    with SessionLocal() as db:
        animals = list_animals(db, query="Amora")
        assert len(animals) == 1
        photos = animals[0].photos
        assert len(photos) == 2
        first_id, second_id = photos[0].id, photos[1].id

    # Served publicly as downscaled WebP (max 1024px)
    anon = TestClient(app)
    media_resp = anon.get(f"/media/animais/{first_id}")
    assert media_resp.status_code == 200
    assert media_resp.headers["content-type"] == "image/webp"
    with Image.open(io.BytesIO(media_resp.content)) as resized:
        assert max(resized.size) <= 1024

    # Switch primary photo and verify public catalog detail renders both
    switch_resp = client.post(
        f"/animais/6/fotos/{second_id}/principal",
        follow_redirects=False,
    )
    assert switch_resp.status_code == 303
    detail_html = anon.get("/adocao/6").text
    assert f"/media/animais/{second_id}" in detail_html

    # Delete first photo
    del_resp = client.post(
        f"/animais/6/fotos/{first_id}/excluir",
        follow_redirects=False,
    )
    assert del_resp.status_code == 303
    assert anon.get(f"/media/animais/{first_id}").status_code == 404


def test_foster_home_crud_prefill_and_adoption_edit() -> None:
    """Test foster CRUD, prefill adoption from foster home, and editing adoptions."""
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

    # Open adoption modal prefilled from foster home #1 (Lucia Schmidt)
    modal_resp = client.get("/modais/nova-adocao?home_id=1&animal_id=4")
    assert modal_resp.status_code == 200
    assert "Lucia Schmidt" in modal_resp.text
    assert "(55) 99611-2233" in modal_resp.text

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

    # Edit the created adoption record
    with SessionLocal() as db:
        adoptions = list_adoptions(db)
        latest_id = adoptions[0].id

    edit_modal = client.get(f"/modais/editar-adocao/{latest_id}")
    assert edit_modal.status_code == 200
    assert "Marcos Pereira" in edit_modal.text

    edit_resp = client.post(
        f"/adocoes/{latest_id}/editar",
        data={
            "adopter_name": "Marcos Pereira Junior",
            "adopter_cpf": "111.222.333-44",
            "adopter_contact": "(55) 99777-0000",
            "adopter_address": "Av. Brasil, 500",
            "adoption_date": "24/11/2026",
        },
        follow_redirects=False,
    )
    assert edit_resp.status_code == 303
    lares_html = client.get("/lares").text
    assert "Marcos Pereira Junior" in lares_html
    assert "Av. Brasil, 500" in lares_html


def test_stock_supplies_create_with_image_filter_and_movement() -> None:
    """Test supplies stock filtering, optional image upload, and accented exit."""
    client = _authenticated_client()

    resp_racao = client.get("/estoque/busca?categoria=Ração")
    assert resp_racao.status_code == 200
    assert "Racao Seca Caes Adultos" in resp_racao.text
    assert "Areia Sanitaria" not in resp_racao.text

    stock_png = _make_test_image(900, 900)
    create_resp = client.post(
        "/estoque/itens",
        data={
            "name": "Shampoo Neutro 5L",
            "category": "Higiene",
            "quantity": "4",
            "unit": "galões",
            "min_quantity": "2",
        },
        files={"imagem": ("shampoo.png", stock_png, "image/png")},
        follow_redirects=False,
    )
    assert create_resp.status_code == 303
    assert "Shampoo Neutro 5L" in client.get("/estoque").text

    with SessionLocal() as db:
        shampoo = [i for i in list_stock(db) if i.name == "Shampoo Neutro 5L"][0]
        shampoo_id = shampoo.id

    img_resp = client.get(f"/media/estoque/{shampoo_id}")
    assert img_resp.status_code == 200
    assert img_resp.headers["content-type"] == "image/webp"

    # Entry movement
    move_in = client.post(
        "/estoque/movimentacao",
        data={"item_id": "2", "movement_type": "Entrada", "quantity": "5"},
        follow_redirects=False,
    )
    assert move_in.status_code == 303
    assert "7 sacos" in client.get("/estoque").text

    # Accented exit movement ("Saída")
    move_out = client.post(
        "/estoque/movimentacao",
        data={"item_id": "2", "movement_type": "Saída", "quantity": "2"},
        follow_redirects=False,
    )
    assert move_out.status_code == 303
    assert "5 sacos" in client.get("/estoque").text


def test_financial_module_and_csv() -> None:
    """Test creating financial entries and exporting CSV accountability report."""
    client = _authenticated_client()

    create_resp = client.post(
        "/financeiro/lancamentos",
        data={
            "tx_type": "Entrada",
            "category": "Doação PIX",
            "description": "Doação comunitária teste",
            "amount": "350,50",
            "payment_method": "PIX",
            "status": "Pago",
            "related_animal": "",
        },
        follow_redirects=False,
    )
    assert create_resp.status_code == 303
    assert "Doação comunitária teste" in client.get("/financeiro").text

    csv_resp = client.get("/financeiro/exportar-csv")
    assert csv_resp.status_code == 200
    assert "Doação comunitária teste" in csv_resp.text


def test_user_profile_settings_avatar_and_local_assets() -> None:
    """Test personal settings, downscaled avatar, admin avatar view, and assets."""
    client = _authenticated_client()

    avatar_png = _make_test_image(800, 800)
    update_resp = client.post(
        "/auth/perfil",
        data={"nome": "Thales Coordenação", "tema": "light"},
        files={"foto": ("avatar.png", avatar_png, "image/png")},
        follow_redirects=False,
    )
    assert update_resp.status_code == 303
    assert 'class="light"' in client.get("/configuracoes").text

    avatar_resp = client.get("/auth/avatar")
    assert avatar_resp.status_code == 200
    assert avatar_resp.headers["content-type"] == "image/webp"
    with Image.open(io.BytesIO(avatar_resp.content)) as resized:
        assert max(resized.size) <= 384

    # Admin users table displays custom avatar endpoint
    admin_users_resp = client.get("/admin/usuarios")
    assert admin_users_resp.status_code == 200
    assert "/auth/avatar/1" in admin_users_resp.text
    assert client.get("/auth/avatar/1").status_code == 200

    for asset_path in [
        "/static/laika-logo.svg",
        "/static/favicon.svg",
        "/static/css/materialdesignicons.min.css",
        "/static/js/htmx.min.js",
    ]:
        assert client.get(asset_path).status_code == 200
