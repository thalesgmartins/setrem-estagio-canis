"""Web routes rendering Jinja2 pages, HTMX fragments, and media for Laika."""

import csv
import io
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from setrem_estagio_canis.api.auth import (
    get_current_user_optional,
    user_has_custom_avatar,
)
from setrem_estagio_canis.core.config import (
    ONG_CITY,
    ONG_WHATSAPP,
    UPLOAD_DIR,
    google_oauth_configured,
)
from setrem_estagio_canis.core.images import MAX_IMAGE_UPLOAD_BYTES, save_resized_webp
from setrem_estagio_canis.database.models import (
    Animal,
    FinancialTransaction,
    StockItem,
    Usuario,
)
from setrem_estagio_canis.database.repository import (
    add_animal_photo,
    add_clinical_event,
    calculate_financial_summary,
    create_adoption_record,
    create_animal,
    create_financial_transaction,
    create_stock_item,
    create_temporary_home,
    delete_adoption_record,
    delete_animal,
    delete_animal_photo,
    delete_temporary_home,
    get_adoption_by_id,
    get_animal_by_id,
    get_animal_photo_by_id,
    get_stock_item_by_id,
    get_temporary_home_by_id,
    list_adoptable_animals,
    list_adoptions,
    list_animals,
    list_financial_transactions,
    list_stock,
    list_temporary_homes,
    list_users,
    mark_transaction_paid,
    register_stock_movement,
    set_primary_animal_photo,
    update_adoption_record,
    update_animal,
    update_temporary_home,
)
from setrem_estagio_canis.database.session import get_db

router = APIRouter(tags=["Frontend"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_ADOPTABLE_STATUSES = {"Disponível para Adoção", "Disponivel para Adocao"}
_FOSTER_STATUSES = {"Lar Temporário", "Lar Temporario"}


@dataclass
class OperationalAlert:
    """Priority operational alert displayed on the dashboard."""

    id: str
    title: str
    subtitle: str
    badge: str
    severity: str
    category: str
    action_label: str
    action_url: str
    use_htmx: bool = False


def calculate_metrics(animals: list[Animal], stock: list[StockItem]) -> dict[str, int]:
    """Calculate operational key indicators for the dashboard."""
    dogs = sum(1 for a in animals if a.species.lower() == "canina")
    cats = sum(1 for a in animals if a.species.lower() == "felina")
    in_foster = sum(1 for a in animals if a.status in _FOSTER_STATUSES)
    available = sum(1 for a in animals if a.status in _ADOPTABLE_STATUSES)
    adopted = sum(1 for a in animals if a.status == "Adotado")
    critical_stock = sum(1 for s in stock if s.status == "Estoque Critico")

    return {
        "total_animals": len(animals),
        "dogs_count": dogs,
        "cats_count": cats,
        "available_count": available,
        "active_foster_homes": in_foster,
        "in_foster_count": in_foster,
        "critical_stock_count": critical_stock,
        "stock_alerts_count": critical_stock,
        "adoptions_count": adopted,
    }


def get_priority_alerts(
    stock: list[StockItem],
    transactions: list[FinancialTransaction] | None = None,
) -> list[OperationalAlert]:
    """Build operational alerts for low stock and pending clinic bills."""
    alerts: list[OperationalAlert] = []
    for item in stock:
        if item.status == "Estoque Critico":
            alerts.append(
                OperationalAlert(
                    id=f"stock-{item.id}",
                    title=item.name,
                    subtitle=(
                        f"Saldo: {item.quantity} {item.unit} "
                        f"(mínimo: {item.min_quantity} {item.unit})"
                    ),
                    badge="Estoque Baixo",
                    severity="critical",
                    category="Estoque",
                    action_label="Repor",
                    action_url="/estoque",
                )
            )

    for tx in transactions or []:
        if tx.tx_type in {"Saída", "Saida"} and tx.status == "Pendente":
            alerts.append(
                OperationalAlert(
                    id=f"fin-{tx.id}",
                    title=tx.description,
                    subtitle=f"{tx.category} · {tx.amount_brl}",
                    badge="Conta Pendente",
                    severity="warning",
                    category="Financeiro",
                    action_label="Ver Financeiro",
                    action_url="/financeiro",
                )
            )
    return alerts


def _auth_gate(
    request: Request, db: Session
) -> tuple[Usuario | None, RedirectResponse | None]:
    """Check session cookie and return either an active user or a redirect."""
    user = get_current_user_optional(request, db)
    if user is None:
        return None, RedirectResponse(url="/login", status_code=303)
    if not user.ativo:
        resp = RedirectResponse(
            url="/login?erro=Conta+desativada+pela+coordenação.",
            status_code=303,
        )
        resp.delete_cookie("access_token")
        return None, resp
    if user.role == "pendente":
        return None, RedirectResponse(url="/aguardando-aprovacao", status_code=303)
    return user, None


def _base_context(
    user: Usuario, active_page: str, page_title: str
) -> dict[str, object]:
    """Build shared template context for authenticated pages."""
    return {
        "current_user": user,
        "tem_avatar": user_has_custom_avatar(user.id),
        "active_page": active_page,
        "page_title": page_title,
    }


def _parse_amount_to_cents(raw_value: str) -> int:
    """Parse Brazilian or decimal currency input into integer cents."""
    cleaned = raw_value.strip().replace("R$", "").replace(" ", "")
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="Valor financeiro inválido."
        ) from exc
    return max(0, round(value * 100))


def _location_options(db: Session) -> list[str]:
    """Return selectable locations exclusively from registered foster homes."""
    return [f"{h.volunteer_name} ({h.neighborhood})" for h in list_temporary_homes(db)]


async def _store_animal_uploads(
    db: Session, animal_id: int, fotos: list[UploadFile]
) -> None:
    """Downscale and store uploaded photos for an animal."""
    animals_dir = UPLOAD_DIR / "animals"
    for upload in fotos:
        if not upload or not upload.filename:
            continue
        raw = await upload.read(MAX_IMAGE_UPLOAD_BYTES + 1)
        if not raw or len(raw) > MAX_IMAGE_UPLOAD_BYTES:
            continue
        filename = f"animal_{animal_id}_{uuid.uuid4().hex[:10]}.webp"
        dest = animals_dir / filename
        if save_resized_webp(raw, dest, max_dimension=1080, quality=82, square=True):
            add_animal_photo(db, animal_id=animal_id, filename=filename)


# ---------------------------------------------------------------------------
# Public Media Routes (Animal Photos & Stock Thumbnails)
# ---------------------------------------------------------------------------


@router.get("/media/animais/{photo_id}")
def serve_animal_photo(
    photo_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Serve a downscaled WebP photo of an animal (public for adoption catalog)."""
    photo = get_animal_photo_by_id(db, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Foto não encontrada.")
    path = UPLOAD_DIR / "animals" / photo.filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Arquivo de foto não encontrado.")
    return Response(
        content=path.read_bytes(),
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/media/estoque/{item_id}")
def serve_stock_photo(
    item_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Serve a downscaled WebP thumbnail for a stock item."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    item = get_stock_item_by_id(db, item_id)
    if item is None or not item.image_filename:
        raise HTTPException(status_code=404, detail="Imagem não encontrada.")
    path = UPLOAD_DIR / "stock" / item.image_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Arquivo de imagem não encontrado.")
    return Response(
        content=path.read_bytes(),
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ---------------------------------------------------------------------------
# Public Routes (Login, Pending Approval, Public Adoption Catalog)
# ---------------------------------------------------------------------------


@router.get("/login", response_model=None)
def login_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    erro: str | None = None,
) -> HTMLResponse | RedirectResponse:
    """Render login page or redirect to dashboard when already authenticated."""
    user = get_current_user_optional(request, db)
    if user is not None and user.ativo:
        if user.role == "pendente":
            return RedirectResponse(url="/aguardando-aprovacao", status_code=303)
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "erro": erro or request.query_params.get("erro"),
            "google_oauth_ativo": google_oauth_configured(),
        },
    )


@router.get("/aguardando-aprovacao", response_model=None)
def pending_approval_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse | RedirectResponse:
    """Display waiting room screen for first-time Google users pending approval."""
    user = get_current_user_optional(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    if user.ativo and user.role in {"admin", "voluntario"}:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="aguardando_aprovacao.html",
        context={"current_user": user},
    )


@router.get("/adocao", response_class=HTMLResponse)
def public_adoption_catalog(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    """Render the public adoption catalog (no login required)."""
    animals = list_adoptable_animals(db)
    return templates.TemplateResponse(
        request=request,
        name="catalogo_adocao.html",
        context={
            "animals": animals,
            "ong_whatsapp": ONG_WHATSAPP,
            "ong_city": ONG_CITY,
        },
    )


@router.get("/adocao/busca", response_class=HTMLResponse)
def public_adoption_search(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    especie: str = "",
    porte: str = "",
) -> HTMLResponse:
    """Filter public adoption catalog cards via HTMX."""
    animals = list_adoptable_animals(db, species=especie, size=porte)
    return templates.TemplateResponse(
        request=request,
        name="fragments/catalogo_cards.html",
        context={"animals": animals, "ong_whatsapp": ONG_WHATSAPP},
    )


@router.get("/adocao/{animal_id}", response_class=HTMLResponse)
def public_adoption_detail(
    animal_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    """Render public detail modal with photo gallery for an adoptable animal."""
    animal = get_animal_by_id(db, animal_id)
    if animal is None or animal.status not in _ADOPTABLE_STATUSES:
        raise HTTPException(
            status_code=404, detail="Animal não disponível para adoção."
        )
    return templates.TemplateResponse(
        request=request,
        name="fragments/catalogo_detail.html",
        context={"animal": animal, "ong_whatsapp": ONG_WHATSAPP},
    )


# ---------------------------------------------------------------------------
# Authenticated Operational Routes
# ---------------------------------------------------------------------------


@router.get("/", response_model=None)
def index(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse | RedirectResponse:
    """Render main operational dashboard or redirect unauthenticated users."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    animals = list_animals(db)
    stock_items = list_stock(db)
    foster_homes = list_temporary_homes(db)
    transactions = list_financial_transactions(db)
    metrics = calculate_metrics(animals, stock_items)
    alerts = get_priority_alerts(stock_items, transactions)
    fin_summary = calculate_financial_summary(transactions)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            **_base_context(user, "dashboard", "Visão Geral"),
            "metrics": metrics,
            "animals": animals[:5],
            "foster_homes": foster_homes,
            "alerts": alerts,
            "fin_summary": fin_summary,
        },
    )


@router.get("/animais", response_model=None)
def animals_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse | RedirectResponse:
    """Render the dedicated animal management directory."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="animais.html",
        context={
            **_base_context(user, "animais", "Animais"),
            "animals": list_animals(db),
            "msg_ok": request.query_params.get("ok"),
        },
    )


@router.post("/animais")
async def create_animal_route(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    name: Annotated[str, Form()],
    species: Annotated[str, Form()],
    size: Annotated[str, Form()],
    location: Annotated[str, Form()] = "",
    rescue_notes: Annotated[str, Form()] = "",
    breed: Annotated[str, Form()] = "Sem Raça Definida",
    age_approx: Annotated[str, Form()] = "A avaliar",
    gender: Annotated[str, Form()] = "A avaliar",
    status: Annotated[str, Form()] = "Acolhido",
    neutered: Annotated[str | None, Form()] = None,
    temperament: Annotated[str, Form()] = "",
    fotos: Annotated[list[UploadFile] | None, File()] = None,
) -> RedirectResponse:
    """Persist a new rescued animal along with optional downscaled photos."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    animal = create_animal(
        db=db,
        name=name,
        species=species,
        size=size,
        location=location or "Não informado",
        rescue_notes=rescue_notes,
        breed=breed,
        age_approx=age_approx,
        gender=gender,
        status=status,
        neutered=neutered == "on",
        temperament=temperament,
    )
    if fotos:
        await _store_animal_uploads(db, animal.id, fotos)

    return RedirectResponse(url="/animais?ok=Animal+cadastrado", status_code=303)


@router.get("/animais/busca", response_class=HTMLResponse)
def search_animals(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    termo: str = "",
    status_filtro: str = "",
) -> HTMLResponse:
    """Filter animals dynamically using HTMX partial requests."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")

    filtered = list_animals(db, query=termo, status_filter=status_filtro)
    return templates.TemplateResponse(
        request=request,
        name="fragments/animal_table.html",
        context={"animals": filtered},
    )


@router.get("/animais/{animal_id}", response_model=None)
def animal_detail_page(
    animal_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse | RedirectResponse:
    """Render full editable management page for a single animal."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    animal = get_animal_by_id(db, animal_id)
    if animal is None:
        raise HTTPException(status_code=404, detail="Animal não encontrado.")

    return templates.TemplateResponse(
        request=request,
        name="animal_editar.html",
        context={
            **_base_context(user, "animais", f"Animal · {animal.name}"),
            "animal": animal,
            "location_options": _location_options(db),
            "msg_ok": request.query_params.get("ok"),
        },
    )


@router.post("/animais/{animal_id}/editar")
def edit_animal_route(
    animal_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    name: Annotated[str, Form()],
    species: Annotated[str, Form()],
    breed: Annotated[str, Form()],
    size: Annotated[str, Form()],
    age_approx: Annotated[str, Form()],
    gender: Annotated[str, Form()],
    status: Annotated[str, Form()],
    location: Annotated[str, Form()] = "",
    temperament: Annotated[str, Form()] = "",
    rescue_notes: Annotated[str, Form()] = "",
    neutered: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    """Save edits to an animal (including foster home / status transfer)."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    updated = update_animal(
        db=db,
        animal_id=animal_id,
        updates={
            "name": name,
            "species": species,
            "breed": breed,
            "size": size,
            "age_approx": age_approx,
            "gender": gender,
            "status": status,
            "location": location,
            "temperament": temperament,
            "rescue_notes": rescue_notes,
            "neutered": neutered == "on",
        },
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Animal não encontrado.")

    return RedirectResponse(
        url=f"/animais/{animal_id}?ok=Alterações+salvas",
        status_code=303,
    )


@router.post("/animais/{animal_id}/fotos")
async def upload_animal_photos_route(
    animal_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    fotos: Annotated[list[UploadFile], File()],
) -> RedirectResponse:
    """Upload one or more downscaled photos for an existing animal."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    if get_animal_by_id(db, animal_id) is None:
        raise HTTPException(status_code=404, detail="Animal não encontrado.")

    await _store_animal_uploads(db, animal_id, fotos)
    return RedirectResponse(
        url=f"/animais/{animal_id}?ok=Fotos+adicionadas",
        status_code=303,
    )


@router.post("/animais/{animal_id}/fotos/{photo_id}/principal")
def set_primary_photo_route(
    animal_id: int,
    photo_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    """Mark a photo as the primary cover photo for an animal."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    set_primary_animal_photo(db, animal_id=animal_id, photo_id=photo_id)
    return RedirectResponse(
        url=f"/animais/{animal_id}?ok=Foto+principal+atualizada",
        status_code=303,
    )


@router.post("/animais/{animal_id}/fotos/{photo_id}/excluir")
def delete_animal_photo_route(
    animal_id: int,
    photo_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    """Delete a photo from an animal and remove its file from disk."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    filename = delete_animal_photo(db, animal_id=animal_id, photo_id=photo_id)
    if filename:
        file_path = UPLOAD_DIR / "animals" / filename
        if file_path.exists():
            file_path.unlink(missing_ok=True)
    return RedirectResponse(
        url=f"/animais/{animal_id}?ok=Foto+removida",
        status_code=303,
    )


@router.post("/animais/{animal_id}/excluir")
def delete_animal_route(
    animal_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    """Remove an animal record and redirect back to the animals directory."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    delete_animal(db, animal_id)
    return RedirectResponse(url="/animais?ok=Registro+removido", status_code=303)


@router.post("/animais/{animal_id}/atendimentos")
def add_clinical_event_route(
    request: Request,
    animal_id: int,
    db: Annotated[Session, Depends(get_db)],
    title: Annotated[str, Form()],
    veterinarian: Annotated[str, Form()],
    notes: Annotated[str, Form()],
) -> RedirectResponse:
    """Persist a veterinary visit or care note and reload the animal page."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    created = add_clinical_event(
        db=db,
        animal_id=animal_id,
        title=title,
        veterinarian=veterinarian,
        notes=notes,
        date_str=datetime.now().strftime("%d/%m/%Y"),
    )
    if created is None:
        raise HTTPException(status_code=404, detail="Animal não encontrado.")

    return RedirectResponse(
        url=f"/animais/{animal_id}?ok=Registro+de+consulta+salvo",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# Stock & Supplies Routes
# ---------------------------------------------------------------------------


@router.get("/estoque", response_model=None)
def stock_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse | RedirectResponse:
    """Render the NGO supplies and food inventory screen."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="estoque.html",
        context={
            **_base_context(user, "estoque", "Estoque"),
            "stock_items": list_stock(db),
            "msg_ok": request.query_params.get("ok"),
        },
    )


@router.get("/estoque/busca", response_class=HTMLResponse)
def search_stock(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    categoria: str = "",
    termo: str = "",
) -> HTMLResponse:
    """Filter inventory items by category and search query."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")

    filtered = list_stock(db, category=categoria, query=termo)
    return templates.TemplateResponse(
        request=request,
        name="fragments/stock_table.html",
        context={"stock_items": filtered},
    )


@router.post("/estoque/itens")
async def create_stock_item_route(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    name: Annotated[str, Form()],
    category: Annotated[str, Form()],
    quantity: Annotated[int, Form()],
    unit: Annotated[str, Form()],
    min_quantity: Annotated[int, Form()] = 2,
    imagem: Annotated[UploadFile | None, File()] = None,
) -> RedirectResponse:
    """Register a new item in NGO supplies stock with optional thumbnail."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    image_filename: str | None = None
    if imagem and imagem.filename:
        raw = await imagem.read(MAX_IMAGE_UPLOAD_BYTES + 1)
        if raw and len(raw) <= MAX_IMAGE_UPLOAD_BYTES:
            candidate = f"stock_{uuid.uuid4().hex[:10]}.webp"
            dest = UPLOAD_DIR / "stock" / candidate
            if save_resized_webp(raw, dest, max_dimension=512, quality=82, square=True):
                image_filename = candidate

    create_stock_item(
        db=db,
        name=name,
        category=category,
        quantity=quantity,
        unit=unit,
        min_quantity=min_quantity,
        image_filename=image_filename,
    )
    return RedirectResponse(url="/estoque?ok=Item+cadastrado", status_code=303)


@router.post("/estoque/movimentacao")
def register_stock_movement_route(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    item_id: Annotated[int, Form()],
    movement_type: Annotated[str, Form()],
    quantity: Annotated[int, Form()],
) -> RedirectResponse:
    """Apply an inventory entry or exit and redirect back to stock view."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    register_stock_movement(
        db=db,
        item_id=item_id,
        movement_type=movement_type,
        quantity=quantity,
    )
    return RedirectResponse(url="/estoque?ok=Saldo+atualizado", status_code=303)


# ---------------------------------------------------------------------------
# Temporary Foster Homes & Adoptions Routes
# ---------------------------------------------------------------------------


@router.get("/lares", response_model=None)
def foster_and_adoptions_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse | RedirectResponse:
    """Render the temporary homes and adoptions screen."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    animals = list_animals(db)
    homes = list_temporary_homes(db)
    home_animals_map: dict[int, list[Animal]] = {}
    for home in homes:
        matched = [
            a
            for a in animals
            if home.volunteer_name.lower() in a.location.lower()
            and a.status != "Adotado"
        ]
        home_animals_map[home.id] = matched

    return templates.TemplateResponse(
        request=request,
        name="lares.html",
        context={
            **_base_context(user, "lares", "Lares e Adoções"),
            "foster_homes": homes,
            "home_animals_map": home_animals_map,
            "adoptions": list_adoptions(db),
            "msg_ok": request.query_params.get("ok"),
        },
    )


@router.post("/lares")
def create_foster_home_route(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    volunteer_name: Annotated[str, Form()],
    contact: Annotated[str, Form()],
    neighborhood: Annotated[str, Form()],
    capacity: Annotated[int, Form()] = 1,
) -> RedirectResponse:
    """Register a new volunteer temporary home."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    create_temporary_home(
        db=db,
        volunteer_name=volunteer_name,
        contact=contact,
        neighborhood=neighborhood,
        capacity=capacity,
    )
    return RedirectResponse(url="/lares?ok=Lar+temporário+cadastrado", status_code=303)


@router.post("/lares/{home_id}/editar")
def update_foster_home_route(
    home_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    volunteer_name: Annotated[str, Form()],
    contact: Annotated[str, Form()],
    neighborhood: Annotated[str, Form()],
    capacity: Annotated[int, Form()] = 1,
) -> RedirectResponse:
    """Update an existing volunteer temporary home."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    update_temporary_home(
        db=db,
        home_id=home_id,
        volunteer_name=volunteer_name,
        contact=contact,
        neighborhood=neighborhood,
        capacity=capacity,
    )
    return RedirectResponse(url="/lares?ok=Lar+atualizado", status_code=303)


@router.post("/lares/{home_id}/excluir")
def delete_foster_home_route(
    home_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    """Remove a volunteer temporary home."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    delete_temporary_home(db, home_id)
    return RedirectResponse(url="/lares?ok=Lar+removido", status_code=303)


@router.post("/adocoes")
def create_adoption_route(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    animal_id: Annotated[int, Form()],
    adopter_name: Annotated[str, Form()],
    adopter_cpf: Annotated[str, Form()],
    adopter_contact: Annotated[str, Form()],
    adopter_address: Annotated[str, Form()],
) -> RedirectResponse:
    """Register an adoption and mark the animal as Adopted."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    create_adoption_record(
        db=db,
        animal_id=animal_id,
        adopter_name=adopter_name,
        adopter_cpf=adopter_cpf,
        adopter_contact=adopter_contact,
        adopter_address=adopter_address,
        adoption_date=datetime.now().strftime("%d/%m/%Y"),
    )
    return RedirectResponse(url="/lares?ok=Adoção+registrada", status_code=303)


@router.post("/adocoes/{adoption_id}/editar")
def edit_adoption_route(
    adoption_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    adopter_name: Annotated[str, Form()],
    adopter_cpf: Annotated[str, Form()],
    adopter_contact: Annotated[str, Form()],
    adopter_address: Annotated[str, Form()],
    adoption_date: Annotated[str, Form()] = "",
) -> RedirectResponse:
    """Update an existing adoption record."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    update_adoption_record(
        db=db,
        adoption_id=adoption_id,
        adopter_name=adopter_name,
        adopter_cpf=adopter_cpf,
        adopter_contact=adopter_contact,
        adopter_address=adopter_address,
        adoption_date=adoption_date,
    )
    return RedirectResponse(url="/lares?ok=Adoção+atualizada", status_code=303)


@router.post("/adocoes/{adoption_id}/excluir")
def delete_adoption_route(
    adoption_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    """Delete an adoption record."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    delete_adoption_record(db, adoption_id)
    return RedirectResponse(url="/lares?ok=Adoção+removida", status_code=303)


# ---------------------------------------------------------------------------
# Financial Module Routes
# ---------------------------------------------------------------------------


@router.get("/financeiro", response_model=None)
def financial_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse | RedirectResponse:
    """Render the NGO financial control and accountability dashboard."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    transactions = list_financial_transactions(db)
    summary = calculate_financial_summary(transactions)
    return templates.TemplateResponse(
        request=request,
        name="financeiro.html",
        context={
            **_base_context(user, "financeiro", "Financeiro"),
            "transactions": transactions,
            "summary": summary,
        },
    )


@router.get("/financeiro/busca", response_class=HTMLResponse)
def search_financial(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    tipo: str = "",
    categoria: str = "",
) -> HTMLResponse:
    """Filter financial transactions via HTMX."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")

    transactions = list_financial_transactions(db, tx_type=tipo, category=categoria)
    return templates.TemplateResponse(
        request=request,
        name="fragments/financial_table.html",
        context={"transactions": transactions},
    )


@router.post("/financeiro/lancamentos")
def create_financial_route(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    tx_type: Annotated[str, Form()],
    category: Annotated[str, Form()],
    description: Annotated[str, Form()],
    amount: Annotated[str, Form()],
    payment_method: Annotated[str, Form()] = "PIX",
    status: Annotated[str, Form()] = "Pago",
    related_animal: Annotated[str, Form()] = "",
) -> RedirectResponse:
    """Create a new income or expense record for the NGO."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    normalized_type = "Entrada" if tx_type == "Entrada" else "Saida"
    tx = FinancialTransaction(
        tx_date=datetime.now().strftime("%d/%m/%Y"),
        tx_type=normalized_type,
        category=category.strip(),
        description=description.strip(),
        amount_cents=_parse_amount_to_cents(amount),
        payment_method=payment_method.strip() or "PIX",
        status=status if status in {"Pago", "Pendente"} else "Pago",
        related_animal=related_animal.strip() or None,
        created_by=user.email,
    )
    create_financial_transaction(db, tx)
    return RedirectResponse(url="/financeiro", status_code=303)


@router.post("/financeiro/lancamentos/{tx_id}/pagar")
def mark_financial_paid_route(
    tx_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    """Mark a pending expense as paid."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    mark_transaction_paid(db, tx_id)
    return RedirectResponse(url="/financeiro", status_code=303)


@router.get("/financeiro/exportar-csv")
def export_financial_csv(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Export NGO financial transactions as a UTF-8 CSV for accountability."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")

    transactions = list_financial_transactions(db)
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(
        [
            "Data",
            "Tipo",
            "Categoria",
            "Descrição",
            "Animal",
            "Forma de Pagamento",
            "Status",
            "Valor",
        ]
    )
    for tx in transactions:
        writer.writerow(
            [
                tx.tx_date,
                tx.tx_type,
                tx.category,
                tx.description,
                tx.related_animal or "",
                tx.payment_method,
                tx.status,
                tx.amount_brl,
            ]
        )

    return Response(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="prestacao-contas-laika.csv"'
        },
    )


# ---------------------------------------------------------------------------
# Personal Settings & Admin Users Screens
# ---------------------------------------------------------------------------


@router.get("/configuracoes", response_model=None)
def settings_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse | RedirectResponse:
    """Render personal account settings (name, avatar, and UI theme)."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="configuracoes.html",
        context={
            **_base_context(user, "configuracoes", "Configurações"),
            "msg_ok": request.query_params.get("ok"),
        },
    )


@router.get("/admin/usuarios", response_model=None)
def admin_users_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse | RedirectResponse:
    """Render user approval and permission management page (admins only)."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)
    if user.role != "admin":
        return RedirectResponse(url="/", status_code=303)

    users = list_users(db)
    custom_avatars = {u.id: user_has_custom_avatar(u.id) for u in users}
    return templates.TemplateResponse(
        request=request,
        name="admin_usuarios.html",
        context={
            **_base_context(user, "usuarios", "Usuários e Permissões"),
            "users": users,
            "custom_avatars": custom_avatars,
            "msg_ok": request.query_params.get("ok"),
            "msg_erro": request.query_params.get("erro"),
        },
    )


# ---------------------------------------------------------------------------
# Global Search, Modals & Printable Adoption Term
# ---------------------------------------------------------------------------


@router.get("/busca-global", response_class=HTMLResponse)
def global_search(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    q: str = "",
) -> HTMLResponse:
    """Search across animals and stock items via HTMX."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")

    query = q.strip()
    if len(query) < 2:
        return HTMLResponse("")

    matched_animals = list_animals(db, query=query)
    matched_stock = list_stock(db, query=query)
    return templates.TemplateResponse(
        request=request,
        name="fragments/global_search.html",
        context={
            "query": query,
            "animals": matched_animals[:4],
            "stock_items": matched_stock[:4],
        },
    )


@router.get("/modais/novo-resgate", response_class=HTMLResponse)
def modal_new_rescue(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    """Render modal form for registering a new animal."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    return templates.TemplateResponse(
        request=request,
        name="fragments/modal_new_rescue.html",
        context={"location_options": _location_options(db)},
    )


@router.get("/modais/novo-item-estoque", response_class=HTMLResponse)
def modal_new_stock_item(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    """Render modal form for creating a new stock item."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    return templates.TemplateResponse(
        request=request, name="fragments/modal_new_stock_item.html", context={}
    )


@router.get("/modais/movimentacao-estoque", response_class=HTMLResponse)
def modal_stock_movement(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    item_id: int | None = None,
) -> HTMLResponse:
    """Render modal form for logging a stock entry or exit."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    return templates.TemplateResponse(
        request=request,
        name="fragments/modal_stock_movement.html",
        context={"stock_items": list_stock(db), "selected_item_id": item_id},
    )


@router.get("/modais/novo-lar", response_class=HTMLResponse)
def modal_new_foster_home(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    """Render modal form for registering a new foster home."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    return templates.TemplateResponse(
        request=request,
        name="fragments/modal_foster_home.html",
        context={"home": None},
    )


@router.get("/modais/editar-lar/{home_id}", response_class=HTMLResponse)
def modal_edit_foster_home(
    home_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    """Render modal form for editing an existing foster home."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    home = get_temporary_home_by_id(db, home_id)
    if home is None:
        raise HTTPException(status_code=404, detail="Lar temporário não encontrado.")
    return templates.TemplateResponse(
        request=request,
        name="fragments/modal_foster_home.html",
        context={"home": home},
    )


@router.get("/modais/nova-adocao", response_class=HTMLResponse)
def modal_new_adoption(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    home_id: int | None = None,
    animal_id: int | None = None,
) -> HTMLResponse:
    """Render modal form for registering a completed adoption (with foster prefill)."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")

    animals = [a for a in list_animals(db) if a.status != "Adotado"]
    homes = list_temporary_homes(db)
    prefill_home = get_temporary_home_by_id(db, home_id) if home_id else None

    return templates.TemplateResponse(
        request=request,
        name="fragments/modal_new_adoption.html",
        context={
            "animals": animals,
            "foster_homes": homes,
            "prefill_home": prefill_home,
            "selected_animal_id": animal_id,
        },
    )


@router.get("/modais/editar-adocao/{adoption_id}", response_class=HTMLResponse)
def modal_edit_adoption(
    adoption_id: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    """Render modal form for editing an existing adoption record."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    adoption = get_adoption_by_id(db, adoption_id)
    if adoption is None:
        raise HTTPException(status_code=404, detail="Adoção não encontrada.")
    return templates.TemplateResponse(
        request=request,
        name="fragments/modal_edit_adoption.html",
        context={"adoption": adoption},
    )


@router.get("/modais/novo-lancamento", response_class=HTMLResponse)
def modal_new_financial(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    """Render modal form for registering a financial income or expense."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    return templates.TemplateResponse(
        request=request,
        name="fragments/modal_new_financial.html",
        context={"animals": list_animals(db)},
    )


@router.get("/termo-adocao/{animal_id}", response_class=HTMLResponse)
def generate_adoption_term(
    request: Request,
    animal_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    """Render a printable adoption agreement term for a specific animal."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")

    animal = get_animal_by_id(db, animal_id)
    if animal is None:
        raise HTTPException(
            status_code=404,
            detail=f"Animal com identificador {animal_id} não encontrado.",
        )

    return templates.TemplateResponse(
        request=request,
        name="termo_adocao.html",
        context={"animal": animal},
    )
