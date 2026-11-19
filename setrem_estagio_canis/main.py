"""Main FastAPI application for the Canis operational management system."""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from setrem_estagio_canis.mock_data import (
    Animal,
    StockItem,
    get_mock_adoptions,
    get_mock_animals,
    get_mock_stock,
    get_mock_temporary_homes,
)

_LOGGER = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="Canis - Gestão Operacional para Proteção Animal",
    description=(
        "Sistema de gestão de resgates, prontuários e insumos da ONG Patas e Pelos"
    ),
    version="0.1.0",
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def calculate_metrics(animals: list[Animal], stock: list[StockItem]) -> dict[str, int]:
    """Calculate operational key indicators for the dashboard.

    Args:
        animals: List of registered animals.
        stock: List of stock items.

    Returns:
        Dictionary containing calculated summary metrics.
    """
    dogs = sum(1 for a in animals if a.species.lower() == "canina")
    cats = sum(1 for a in animals if a.species.lower() == "felina")
    critical_stock = sum(1 for s in stock if s.status == "Estoque Critico")

    # In prototype, mock 4 booster alerts within 30 days
    return {
        "total_animals": len(animals),
        "dogs_count": dogs,
        "cats_count": cats,
        "active_foster_homes": 1,
        "vaccines_due": 2,
        "critical_stock_count": critical_stock,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Render the main application dashboard with initial operational data.

    Args:
        request: FastAPI HTTP request instance.

    Returns:
        Rendered HTML response of the dashboard.
    """
    animals = get_mock_animals()
    stock_items = get_mock_stock()
    foster_homes = get_mock_temporary_homes()
    adoptions = get_mock_adoptions()
    metrics = calculate_metrics(animals, stock_items)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "metrics": metrics,
            "animals": animals,
            "stock_items": stock_items,
            "foster_homes": foster_homes,
            "adoptions": adoptions,
        },
    )


@app.get("/animais/busca", response_class=HTMLResponse)
def search_animals(
    request: Request, termo: str = "", status_filtro: str = ""
) -> HTMLResponse:
    """Filter animals dynamically using HTMX partial requests.

    Args:
        request: FastAPI HTTP request instance.
        termo: Search keyword matching name, breed, or location.
        status_filtro: Exact status filter.

    Returns:
        Rendered HTML table fragment of matching animals.
    """
    query = termo.strip().lower()
    selected_status = status_filtro.strip()
    all_animals = get_mock_animals()

    filtered = []
    for animal in all_animals:
        matches_query = (
            not query
            or query in animal.name.lower()
            or query in animal.breed.lower()
            or query in animal.species.lower()
            or query in animal.location.lower()
        )
        matches_status = not selected_status or animal.status == selected_status

        if matches_query and matches_status:
            filtered.append(animal)

    return templates.TemplateResponse(
        request=request,
        name="fragments/animal_table.html",
        context={"animals": filtered},
    )


@app.get("/animais/{animal_id}/prontuario", response_class=HTMLResponse)
def get_animal_record(request: Request, animal_id: int) -> HTMLResponse:
    """Render clinical record modal for a specific animal.

    Args:
        request: FastAPI HTTP request instance.
        animal_id: Unique integer identifier of the animal.

    Returns:
        Rendered HTML modal fragment.

    Raises:
        HTTPException: If the specified animal identifier does not exist.
    """
    all_animals = get_mock_animals()
    animal = next((a for a in all_animals if a.id == animal_id), None)

    if animal is None:
        raise HTTPException(
            status_code=404,
            detail=f"Animal com identificador {animal_id} nao encontrado.",
        )

    return templates.TemplateResponse(
        request=request,
        name="fragments/animal_detail.html",
        context={"animal": animal},
    )


@app.get("/estoque/busca", response_class=HTMLResponse)
def search_stock(request: Request, categoria: str = "") -> HTMLResponse:
    """Filter inventory items by category.

    Args:
        request: FastAPI HTTP request instance.
        categoria: Category filter term.

    Returns:
        Rendered HTML table fragment of stock items.
    """
    selected_cat = categoria.strip().lower()
    all_stock = get_mock_stock()

    if selected_cat:
        filtered = [s for s in all_stock if s.category.lower() == selected_cat]
    else:
        filtered = all_stock

    return templates.TemplateResponse(
        request=request,
        name="fragments/stock_table.html",
        context={"stock_items": filtered},
    )


@app.get("/termo-adocao/{animal_id}", response_class=HTMLResponse)
def generate_adoption_term(request: Request, animal_id: int) -> HTMLResponse:
    """Render a printable adoption agreement term for a specific animal.

    Args:
        request: FastAPI HTTP request instance.
        animal_id: Unique integer identifier of the animal.

    Returns:
        Rendered HTML page ready for printing.

    Raises:
        HTTPException: If the animal does not exist.
    """
    all_animals = get_mock_animals()
    animal = next((a for a in all_animals if a.id == animal_id), None)

    if animal is None:
        raise HTTPException(
            status_code=404,
            detail=f"Animal com identificador {animal_id} nao encontrado.",
        )

    return templates.TemplateResponse(
        request=request,
        name="termo_adocao.html",
        context={"animal": animal},
    )


if __name__ == "__main__":
    import uvicorn

    _LOGGER.info("Iniciando o prototipo Canis na porta 8000...")
    uvicorn.run(
        "setrem_estagio_canis.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
