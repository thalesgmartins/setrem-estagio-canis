"""Web routes rendering Jinja2 pages and HTMX fragments for Canis."""

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
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
    google_oauth_configured,
)
from setrem_estagio_canis.database.models import (
    Animal,
    FinancialTransaction,
    StockItem,
    Usuario,
)
from setrem_estagio_canis.database.repository import (
    add_clinical_event,
    calculate_financial_summary,
    create_animal,
    create_financial_transaction,
    get_animal_by_id,
    list_adoptable_animals,
    list_adoptions,
    list_animals,
    list_financial_transactions,
    list_stock,
    list_temporary_homes,
    list_users,
    mark_transaction_paid,
    register_stock_movement,
)
from setrem_estagio_canis.database.session import get_db

router = APIRouter(tags=["Frontend"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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


@dataclass
class ActivityItem:
    """Recent operational event displayed on the dashboard."""

    timestamp: str
    category: str
    title: str
    detail: str
    action_label: str
    action_url: str
    use_htmx: bool = False


def calculate_metrics(animals: list[Animal], stock: list[StockItem]) -> dict[str, int]:
    """Calculate operational key indicators for the dashboard."""
    dogs = sum(1 for a in animals if a.species.lower() == "canina")
    cats = sum(1 for a in animals if a.species.lower() == "felina")
    in_foster = sum(1 for a in animals if a.status == "Lar Temporario")
    adopted = sum(1 for a in animals if a.status == "Adotado")
    critical_stock = sum(1 for s in stock if s.status == "Estoque Critico")
    expiring_stock = sum(1 for s in stock if s.status == "Vencendo em breve")
    vaccines_due = sum(1 for a in animals for v in a.vaccines if v.status == "Pendente")

    return {
        "total_animals": len(animals),
        "dogs_count": dogs,
        "cats_count": cats,
        "active_foster_homes": in_foster,
        "in_foster_count": in_foster,
        "vaccines_due": vaccines_due,
        "critical_stock_count": critical_stock,
        "stock_alerts_count": critical_stock + expiring_stock,
        "adoptions_count": adopted,
    }


def get_priority_alerts(
    animals: list[Animal], stock: list[StockItem]
) -> list[OperationalAlert]:
    """Build prioritized alerts for expiring stock, low stock, and pending vaccines."""
    alerts: list[OperationalAlert] = []
    for item in stock:
        if item.status == "Estoque Critico":
            alerts.append(
                OperationalAlert(
                    id=f"stock-{item.id}",
                    title=item.name,
                    subtitle=(
                        f"Lote {item.lot_number} | Saldo: {item.quantity} "
                        f"{item.unit} (min. {item.min_quantity})"
                    ),
                    badge="Estoque Baixo",
                    severity="critical",
                    category="Estoque",
                    action_label="Ver Lote",
                    action_url="/estoque",
                )
            )
        elif item.status == "Vencendo em breve":
            alerts.append(
                OperationalAlert(
                    id=f"exp-{item.id}",
                    title=item.name,
                    subtitle=(
                        f"Lote {item.lot_number} | Validade: {item.expiration_date} "
                        f"| {item.quantity} {item.unit}"
                    ),
                    badge="Vencimento < 30d",
                    severity="warning",
                    category="Validade",
                    action_label="Ver Estoque",
                    action_url="/estoque",
                )
            )

    for animal in animals:
        for vac in animal.vaccines:
            if vac.status == "Pendente":
                alerts.append(
                    OperationalAlert(
                        id=f"vac-{animal.id}-{vac.lot}",
                        title=f"Reforco de {vac.name} - {animal.name}",
                        subtitle=(
                            f"Previsto para {vac.next_due_date} | {animal.location}"
                        ),
                        badge="Vacina Pendente",
                        severity="warning",
                        category="Clinica",
                        action_label="Abrir Prontuario",
                        action_url=f"/animais/{animal.id}/prontuario",
                        use_htmx=True,
                    )
                )
    return alerts


def _get_recent_activities() -> list[ActivityItem]:
    """Return recent NGO operational highlights for the dashboard feed."""
    return [
        ActivityItem(
            timestamp="24/09 · 14:30",
            category="Prontuario",
            title="Reavaliacao ortopedica registrada para Pipoca",
            detail="Dra. Camila Ferreira atualizou dosagem de Meloxicam 2mg.",
            action_label="Prontuario",
            action_url="/animais/1/prontuario",
            use_htmx=True,
        ),
        ActivityItem(
            timestamp="21/09 · 10:15",
            category="Resgate",
            title="Entrada de Mel no Gatil Central - Modulo B",
            detail="Teste rapido FIV/FeLV negativo e 1a dose V4 aplicada.",
            action_label="Prontuario",
            action_url="/animais/3/prontuario",
            use_htmx=True,
        ),
        ActivityItem(
            timestamp="15/09 · 16:40",
            category="Adocao",
            title="Termo de adocao emitido para Luna",
            detail="Adotante: Ana Paula de Souza · Acompanhamento ativo.",
            action_label="Ver Termo",
            action_url="/termo-adocao/5",
        ),
        ActivityItem(
            timestamp="20/09 · 11:00",
            category="Financeiro",
            title="Fatura pendente na Clinica Parceira (Pipoca)",
            detail="Valor: R$ 680,00 · Cirurgia ortopedica e internacao.",
            action_label="Financeiro",
            action_url="/financeiro",
        ),
    ]


def _auth_gate(
    request: Request, db: Session
) -> tuple[Usuario | None, RedirectResponse | None]:
    """Check session cookie and return either an active user or a redirect."""
    user = get_current_user_optional(request, db)
    if user is None:
        return None, RedirectResponse(url="/login", status_code=303)
    if not user.ativo:
        resp = RedirectResponse(
            url="/login?erro=Conta+desativada+pela+coordenacao.",
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
            status_code=400, detail="Valor financeiro invalido."
        ) from exc
    return max(0, round(value * 100))


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
    adoptions = list_adoptions(db)
    transactions = list_financial_transactions(db)
    metrics = calculate_metrics(animals, stock_items)
    alerts = get_priority_alerts(animals, stock_items)
    fin_summary = calculate_financial_summary(transactions)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            **_base_context(user, "dashboard", "Visao Geral"),
            "metrics": metrics,
            "animals": animals,
            "stock_items": stock_items,
            "foster_homes": foster_homes,
            "adoptions": adoptions,
            "alerts": alerts,
            "activities": _get_recent_activities(),
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
        },
    )


@router.post("/animais")
def create_animal_route(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    name: Annotated[str, Form()],
    species: Annotated[str, Form()],
    size: Annotated[str, Form()],
    location: Annotated[str, Form()],
    rescue_notes: Annotated[str, Form()],
) -> RedirectResponse:
    """Persist a new rescued animal and redirect to the animals directory."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    create_animal(
        db=db,
        name=name,
        species=species,
        size=size,
        location=location,
        rescue_notes=rescue_notes,
    )
    return RedirectResponse(url="/animais", status_code=303)


@router.get("/prontuarios", response_model=None)
def records_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse | RedirectResponse:
    """Render the clinical records overview screen."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="prontuarios.html",
        context={
            **_base_context(user, "prontuarios", "Prontuarios"),
            "animals": list_animals(db),
        },
    )


@router.get("/estoque", response_model=None)
def stock_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse | RedirectResponse:
    """Render the dedicated stock and supply tracking screen."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="estoque.html",
        context={
            **_base_context(user, "estoque", "Estoque"),
            "stock_items": list_stock(db),
        },
    )


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
    return RedirectResponse(url="/estoque", status_code=303)


@router.get("/lares", response_model=None)
def foster_and_adoptions_page(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse | RedirectResponse:
    """Render the temporary homes and adoptions screen."""
    user, redirect = _auth_gate(request, db)
    if redirect is not None or user is None:
        return redirect or RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="lares.html",
        context={
            **_base_context(user, "lares", "Lares e Adocoes"),
            "foster_homes": list_temporary_homes(db),
            "adoptions": list_adoptions(db),
            "animals": list_animals(db),
        },
    )


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
        raise HTTPException(status_code=401, detail="Nao autenticado.")

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

    tx = FinancialTransaction(
        tx_date=datetime.now().strftime("%d/%m/%Y"),
        tx_type=tx_type if tx_type in {"Entrada", "Saida"} else "Saida",
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
        raise HTTPException(status_code=401, detail="Nao autenticado.")

    transactions = list_financial_transactions(db)
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(
        [
            "Data",
            "Tipo",
            "Categoria",
            "Descricao",
            "Animal",
            "Forma Pagamento",
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
            **_base_context(user, "configuracoes", "Configuracoes"),
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

    return templates.TemplateResponse(
        request=request,
        name="admin_usuarios.html",
        context={
            **_base_context(user, "usuarios", "Usuarios e Permissoes"),
            "users": list_users(db),
            "msg_ok": request.query_params.get("ok"),
            "msg_erro": request.query_params.get("erro"),
        },
    )


# ---------------------------------------------------------------------------
# HTMX Partials, Modals & Printable Adoption Term
# ---------------------------------------------------------------------------


@router.get("/busca-global", response_class=HTMLResponse)
def global_search(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    q: str = "",
) -> HTMLResponse:
    """Search across animals, microchips, and stock lots via HTMX."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Nao autenticado.")

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
        raise HTTPException(status_code=401, detail="Nao autenticado.")

    filtered = list_animals(db, query=termo, status_filter=status_filtro)
    return templates.TemplateResponse(
        request=request,
        name="fragments/animal_table.html",
        context={"animals": filtered},
    )


@router.get("/animais/{animal_id}/prontuario", response_class=HTMLResponse)
def get_animal_record(
    request: Request,
    animal_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    """Render clinical record drawer/modal for a specific animal."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Nao autenticado.")

    animal = get_animal_by_id(db, animal_id)
    if animal is None:
        raise HTTPException(
            status_code=404,
            detail=f"Animal com identificador {animal_id} nao encontrado.",
        )

    return templates.TemplateResponse(
        request=request,
        name="fragments/animal_detail.html",
        context={"animal": animal, "active_tab": "clinico"},
    )


@router.get("/animais/{animal_id}/prontuario/aba/{tab}", response_class=HTMLResponse)
def get_animal_record_tab(
    request: Request,
    animal_id: int,
    tab: str,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    """Render a specific tab inside the animal clinical record via HTMX."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Nao autenticado.")

    animal = get_animal_by_id(db, animal_id)
    if animal is None:
        raise HTTPException(
            status_code=404,
            detail=f"Animal com identificador {animal_id} nao encontrado.",
        )
    if tab not in {"clinico", "vacinas", "lares"}:
        raise HTTPException(status_code=400, detail="Aba de prontuario invalida.")

    return templates.TemplateResponse(
        request=request,
        name="fragments/animal_detail_tabs.html",
        context={"animal": animal, "active_tab": tab},
    )


@router.post("/animais/{animal_id}/atendimentos", response_class=HTMLResponse)
def add_clinical_event_route(
    request: Request,
    animal_id: int,
    db: Annotated[Session, Depends(get_db)],
    title: Annotated[str, Form()],
    veterinarian: Annotated[str, Form()],
    notes: Annotated[str, Form()],
) -> HTMLResponse:
    """Persist a new clinical event and return the refreshed clinical tab."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Nao autenticado.")

    created = add_clinical_event(
        db=db,
        animal_id=animal_id,
        title=title,
        veterinarian=veterinarian,
        notes=notes,
        date_str=datetime.now().strftime("%d/%m/%Y"),
    )
    if created is None:
        raise HTTPException(status_code=404, detail="Animal nao encontrado.")

    animal = get_animal_by_id(db, animal_id)
    return templates.TemplateResponse(
        request=request,
        name="fragments/animal_detail_tabs.html",
        context={"animal": animal, "active_tab": "clinico"},
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
        raise HTTPException(status_code=401, detail="Nao autenticado.")

    filtered = list_stock(db, category=categoria, query=termo)
    return templates.TemplateResponse(
        request=request,
        name="fragments/stock_table.html",
        context={"stock_items": filtered},
    )


@router.get("/modais/novo-resgate", response_class=HTMLResponse)
def modal_new_rescue(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    """Render the modal form for registering a new animal rescue."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Nao autenticado.")
    return templates.TemplateResponse(
        request=request, name="fragments/modal_new_rescue.html", context={}
    )


@router.get("/modais/movimentacao-estoque", response_class=HTMLResponse)
def modal_stock_movement(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    """Render the modal form for logging a stock entry or exit."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Nao autenticado.")
    return templates.TemplateResponse(
        request=request,
        name="fragments/modal_stock_movement.html",
        context={"stock_items": list_stock(db)},
    )


@router.get("/modais/novo-lancamento", response_class=HTMLResponse)
def modal_new_financial(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    """Render the modal form for registering a financial income or expense."""
    user, _ = _auth_gate(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Nao autenticado.")
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
        raise HTTPException(status_code=401, detail="Nao autenticado.")

    animal = get_animal_by_id(db, animal_id)
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
