"""Unit tests for the Canis prototype application endpoints and logic."""

from fastapi.testclient import TestClient

from setrem_estagio_canis.main import app, calculate_metrics
from setrem_estagio_canis.mock_data import (
    get_mock_animals,
    get_mock_stock,
)

client = TestClient(app)


def test_calculate_metrics() -> None:
    """Ensure dashboard metrics are accurately computed from input data."""
    # Arrange
    animals = get_mock_animals()
    stock = get_mock_stock()

    # Act
    metrics = calculate_metrics(animals, stock)

    # Assert
    assert metrics["total_animals"] == len(animals)
    assert metrics["dogs_count"] >= 1
    assert metrics["cats_count"] >= 1
    assert metrics["critical_stock_count"] >= 1


def test_get_index_dashboard() -> None:
    """Test that the index route successfully renders the dashboard."""
    # Act
    response = client.get("/")

    # Assert
    assert response.status_code == 200
    assert "CANIS" in response.text
    assert "Patas e Pelos" in response.text
    assert "Indicadores Operacionais" in response.text


def test_search_animals_by_name() -> None:
    """Test searching animals with a specific name keyword via HTMX endpoint."""
    # Act
    response = client.get("/animais/busca?termo=Pipoca")

    # Assert
    assert response.status_code == 200
    assert "Pipoca" in response.text
    assert "Thor" not in response.text


def test_search_animals_by_status_filter() -> None:
    """Test filtering animals by status category."""
    # Act
    response = client.get("/animais/busca?status_filtro=Lar Temporario")

    # Assert
    assert response.status_code == 200
    assert "Thor" in response.text
    assert "Pipoca" not in response.text


def test_search_animals_not_found() -> None:
    """Test searching with an unmatched term returns not found message."""
    # Act
    response = client.get("/animais/busca?termo=NomeInexistenteXYZ")

    # Assert
    assert response.status_code == 200
    assert "Nenhum animal encontrado" in response.text


def test_get_animal_prontuario_success() -> None:
    """Test retrieving clinical record modal for an existing animal."""
    # Act
    response = client.get("/animais/1/prontuario")

    # Assert
    assert response.status_code == 200
    assert "Prontuario Clinico: Pipoca" in response.text
    assert "Vacina V10" in response.text
    assert "Antirrabica" in response.text


def test_get_animal_prontuario_not_found() -> None:
    """Test 404 response when querying a non-existent animal id."""
    # Act
    response = client.get("/animais/9999/prontuario")

    # Assert
    assert response.status_code == 404
    assert "nao encontrado" in response.text


def test_search_stock_all_and_filtered() -> None:
    """Test stock endpoint returns all items or filtered items."""
    # Act 1: all
    resp_all = client.get("/estoque/busca")
    assert resp_all.status_code == 200
    assert "Simparic" in resp_all.text
    assert "Nobivac" in resp_all.text

    # Act 2: filtered by category
    resp_filtered = client.get("/estoque/busca?categoria=Vacina")
    assert resp_filtered.status_code == 200
    assert "Nobivac" in resp_filtered.text
    assert "Simparic" not in resp_filtered.text


def test_generate_adoption_term_success() -> None:
    """Test generating printable adoption term for an existing animal."""
    # Act
    response = client.get("/termo-adocao/1")

    # Assert
    assert response.status_code == 200
    assert "Termo de Responsabilidade" in response.text
    assert "Pipoca" in response.text


def test_generate_adoption_term_not_found() -> None:
    """Test 404 when generating adoption term for an unknown animal."""
    # Act
    response = client.get("/termo-adocao/9999")

    # Assert
    assert response.status_code == 404


def test_static_logo_available() -> None:
    """Ensure static logo image is accessible via static files mount."""
    # Act
    response = client.get("/static/logo.jpg")

    # Assert
    assert response.status_code == 200
    assert response.headers["content-type"] in ["image/jpeg", "image/jpg"]
