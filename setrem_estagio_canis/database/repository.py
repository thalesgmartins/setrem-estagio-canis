"""Database repositories and idempotent initial seed for the Canis system."""

import unicodedata
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from setrem_estagio_canis.core.config import ADMIN_EMAILS
from setrem_estagio_canis.core.security import hash_password
from setrem_estagio_canis.database.models import (
    AdoptionTerm,
    Animal,
    AnimalPhoto,
    ClinicalEvent,
    FinancialTransaction,
    StockItem,
    TemporaryHome,
    Usuario,
    VaccineRecord,
)


@dataclass
class FinancialSummary:
    """Aggregated financial balance for the NGO."""

    total_income_cents: int
    total_expense_cents: int
    pending_expense_cents: int
    balance_cents: int

    @staticmethod
    def format_brl(cents: int) -> str:
        """Format an integer amount in cents to BRL string."""
        sign = "-" if cents < 0 else ""
        reais = abs(cents) / 100
        formatted = (
            f"{reais:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        )
        return f"{sign}R$ {formatted}"

    @property
    def total_income_brl(self) -> str:
        """Formatted total income in BRL."""
        return self.format_brl(self.total_income_cents)

    @property
    def total_expense_brl(self) -> str:
        """Formatted total expenses in BRL."""
        return self.format_brl(self.total_expense_cents)

    @property
    def pending_expense_brl(self) -> str:
        """Formatted pending expenses in BRL."""
        return self.format_brl(self.pending_expense_cents)

    @property
    def balance_brl(self) -> str:
        """Formatted net balance in BRL."""
        return self.format_brl(self.balance_cents)


# ---------------------------------------------------------------------------
# Users & Access Control
# ---------------------------------------------------------------------------


def get_user_by_id(db: Session, user_id: int) -> Usuario | None:
    """Retrieve a user by primary key."""
    return db.get(Usuario, user_id)


def get_user_by_email(db: Session, email: str) -> Usuario | None:
    """Retrieve a user by normalized lowercase email."""
    return db.scalar(select(Usuario).where(Usuario.email == email.strip().lower()))


def list_users(db: Session) -> list[Usuario]:
    """List all registered users ordered with pending accounts first."""
    users = list(db.scalars(select(Usuario).order_by(Usuario.id.asc())).all())
    order = {"pendente": 0, "admin": 1, "voluntario": 2}
    return sorted(users, key=lambda u: (order.get(u.role, 3), not u.ativo, u.nome))


def create_or_update_google_user(
    db: Session,
    google_sub: str,
    email: str,
    nome: str,
    avatar_url: str | None = None,
) -> Usuario:
    """Resolve a Google OAuth login against existing or pre-registered accounts.

    Emails listed in ADMIN_EMAILS automatically receive the 'admin' role.
    Pre-registered emails keep their assigned role and get linked to Google.
    Unknown emails are created with role='pendente' awaiting admin approval.
    """
    normalized_email = email.strip().lower()
    user = db.scalar(select(Usuario).where(Usuario.google_sub == google_sub))
    if user is None:
        user = get_user_by_email(db, normalized_email)

    if user is not None:
        user.google_sub = google_sub
        if nome and (not user.nome or user.nome == normalized_email.split("@")[0]):
            user.nome = nome
        if avatar_url:
            user.avatar_url = avatar_url
        if normalized_email in ADMIN_EMAILS:
            user.role = "admin"
            user.ativo = True
        db.commit()
        db.refresh(user)
        return user

    initial_role = "admin" if normalized_email in ADMIN_EMAILS else "pendente"
    user = Usuario(
        nome=nome or normalized_email.split("@")[0],
        email=normalized_email,
        google_sub=google_sub,
        avatar_url=avatar_url,
        role=initial_role,
        ativo=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def preregister_user(
    db: Session,
    nome: str,
    email: str,
    role: str = "voluntario",
) -> Usuario:
    """Pre-register or update an authorized volunteer/admin email."""
    normalized_email = email.strip().lower()
    valid_role = role if role in {"admin", "voluntario", "pendente"} else "voluntario"
    existing = get_user_by_email(db, normalized_email)
    if existing is not None:
        existing.nome = nome.strip() or existing.nome
        existing.role = valid_role
        existing.ativo = True
        db.commit()
        db.refresh(existing)
        return existing

    user = Usuario(
        nome=nome.strip() or normalized_email.split("@")[0],
        email=normalized_email,
        role=valid_role,
        ativo=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user_role(db: Session, user_id: int, role: str) -> Usuario | None:
    """Update a user's access role ('admin', 'voluntario', or 'pendente')."""
    if role not in {"admin", "voluntario", "pendente"}:
        return None
    user = get_user_by_id(db, user_id)
    if user is None:
        return None
    user.role = role
    if role in {"admin", "voluntario"}:
        user.ativo = True
    db.commit()
    db.refresh(user)
    return user


def toggle_user_active(db: Session, user_id: int) -> Usuario | None:
    """Toggle active status for a user account."""
    user = get_user_by_id(db, user_id)
    if user is None:
        return None
    user.ativo = not user.ativo
    db.commit()
    db.refresh(user)
    return user


def update_user_profile(
    db: Session,
    user: Usuario,
    nome: str | None = None,
    tema: str | None = None,
) -> Usuario:
    """Update a user's display name and UI theme preference."""
    if nome is not None and nome.strip():
        user.nome = nome.strip()
    if tema in {"dark", "light"}:
        user.tema = tema
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Animals & Clinical Records
# ---------------------------------------------------------------------------


def _fold(text: str) -> str:
    """Normalize accents and case for accent-insensitive filtering."""
    normalized = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def list_animals(
    db: Session,
    query: str = "",
    status_filter: str = "",
) -> list[Animal]:
    """List animals with photos, vaccines, and clinical events eagerly loaded."""
    stmt = (
        select(Animal)
        .options(
            selectinload(Animal.photos),
            selectinload(Animal.vaccines),
            selectinload(Animal.clinical_events),
        )
        .order_by(Animal.id.asc())
    )
    animals = list(db.scalars(stmt).all())
    q = _fold(query)
    st = _fold(status_filter)

    if not q and not st:
        return animals

    return [
        a
        for a in animals
        if (
            not q
            or q in _fold(a.name)
            or q in _fold(a.breed)
            or q in _fold(a.species)
            or q in _fold(a.location)
            or q in _fold(a.microchip)
        )
        and (not st or _fold(a.status) == st)
    ]


def list_adoptable_animals(
    db: Session,
    species: str = "",
    size: str = "",
) -> list[Animal]:
    """List animals publicly available for adoption."""
    animals = [
        a for a in list_animals(db) if _fold(a.status) == "disponivel para adocao"
    ]
    sp = _fold(species)
    sz = _fold(size)

    return [
        a
        for a in animals
        if (not sp or _fold(a.species) == sp)
        and (not sz or _fold(a.size_category) == sz)
    ]


def get_animal_by_id(db: Session, animal_id: int) -> Animal | None:
    """Retrieve a single animal with related photos, vaccines, and clinical events."""
    stmt = (
        select(Animal)
        .where(Animal.id == animal_id)
        .options(
            selectinload(Animal.photos),
            selectinload(Animal.vaccines),
            selectinload(Animal.clinical_events),
        )
    )
    return db.scalar(stmt)


def add_animal_photo(
    db: Session,
    animal_id: int,
    filename: str,
    is_primary: bool = False,
) -> AnimalPhoto:
    """Attach a downscaled photo record to an animal."""
    existing_count = len(
        list(
            db.scalars(
                select(AnimalPhoto).where(AnimalPhoto.animal_id == animal_id)
            ).all()
        )
    )
    photo = AnimalPhoto(
        animal_id=animal_id,
        filename=filename,
        is_primary=is_primary or existing_count == 0,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo


def get_animal_photo_by_id(db: Session, photo_id: int) -> AnimalPhoto | None:
    """Retrieve a single animal photo record by ID."""
    return db.get(AnimalPhoto, photo_id)


def set_primary_animal_photo(db: Session, animal_id: int, photo_id: int) -> bool:
    """Mark one photo as the primary photo for an animal."""
    photos = list(
        db.scalars(select(AnimalPhoto).where(AnimalPhoto.animal_id == animal_id)).all()
    )
    found = False
    for photo in photos:
        if photo.id == photo_id:
            photo.is_primary = True
            found = True
        else:
            photo.is_primary = False
    if found:
        db.commit()
    return found


def delete_animal_photo(db: Session, animal_id: int, photo_id: int) -> str | None:
    """Delete a photo record and return its filename for disk cleanup."""
    photo = db.get(AnimalPhoto, photo_id)
    if photo is None or photo.animal_id != animal_id:
        return None
    filename = photo.filename
    was_primary = photo.is_primary
    db.delete(photo)
    db.commit()

    if was_primary:
        remaining = db.scalar(
            select(AnimalPhoto)
            .where(AnimalPhoto.animal_id == animal_id)
            .order_by(AnimalPhoto.id.asc())
        )
        if remaining is not None:
            remaining.is_primary = True
            db.commit()
    return filename


def create_animal(
    db: Session,
    name: str,
    species: str,
    size: str,
    location: str,
    rescue_notes: str,
    breed: str = "Sem Raça Definida",
    age_approx: str = "A avaliar",
    gender: str = "A avaliar",
    status: str = "Acolhido",
    neutered: bool = False,
    temperament: str = "",
) -> Animal:
    """Persist a newly rescued animal."""
    animal = Animal(
        name=name.strip(),
        species=species.strip(),
        breed=breed.strip() or "Sem Raça Definida",
        size=size.strip(),
        age_approx=age_approx.strip() or "A avaliar",
        gender=gender.strip() or "A avaliar",
        status=status.strip() or "Acolhido",
        intake_date="Hoje",
        neutered=neutered,
        location=location.strip(),
        microchip="",
        rescue_notes=rescue_notes.strip(),
        temperament=temperament.strip() or "Em avaliação comportamental.",
        foster_history_text=f"Entrada: {location.strip()}",
    )
    db.add(animal)
    db.commit()
    db.refresh(animal)
    return animal


def update_animal(
    db: Session,
    animal_id: int,
    updates: dict[str, object],
) -> Animal | None:
    """Update editable fields of an existing animal and log location changes."""
    animal = get_animal_by_id(db, animal_id)
    if animal is None:
        return None

    old_location = animal.location
    for field_name in (
        "name",
        "species",
        "breed",
        "size",
        "age_approx",
        "gender",
        "status",
        "location",
        "temperament",
        "rescue_notes",
    ):
        if field_name in updates:
            setattr(animal, field_name, str(updates[field_name]).strip())

    if "neutered" in updates:
        animal.neutered = bool(updates["neutered"])

    if animal.location != old_location and animal.location:
        history_line = f"Transferido para: {animal.location}"
        if animal.foster_history_text:
            animal.foster_history_text = f"{history_line}\n{animal.foster_history_text}"
        else:
            animal.foster_history_text = history_line

    db.commit()
    db.refresh(animal)
    return animal


def delete_animal(db: Session, animal_id: int) -> bool:
    """Delete an animal record by ID."""
    animal = db.get(Animal, animal_id)
    if animal is None:
        return False
    db.delete(animal)
    db.commit()
    return True


def add_clinical_event(
    db: Session,
    animal_id: int,
    title: str,
    veterinarian: str,
    notes: str,
    date_str: str = "Hoje",
) -> ClinicalEvent | None:
    """Append a clinical event to an animal's record."""
    animal = db.get(Animal, animal_id)
    if animal is None:
        return None
    event = ClinicalEvent(
        animal_id=animal_id,
        date=date_str,
        title=title.strip(),
        category="Atendimento",
        veterinarian=veterinarian.strip(),
        notes=notes.strip(),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


# ---------------------------------------------------------------------------
# Stock & Supplies
# ---------------------------------------------------------------------------


def list_stock(
    db: Session,
    category: str = "",
    query: str = "",
) -> list[StockItem]:
    """List inventory lots with optional category and free-text filters."""
    items = list(db.scalars(select(StockItem).order_by(StockItem.id.asc())).all())
    selected_cat = _fold(category)
    q = _fold(query)
    medicine_cats = {"antibiotico", "anti-inflamatorio", "antiparasitario"}

    filtered: list[StockItem] = []
    for item in items:
        cat_folded = _fold(item.category)
        if selected_cat == "medicamentos":
            matches_cat = cat_folded in medicine_cats
        elif selected_cat:
            matches_cat = cat_folded == selected_cat
        else:
            matches_cat = True

        matches_query = (
            not q
            or q in _fold(item.name)
            or q in _fold(item.lot_number)
            or q in cat_folded
        )
        if matches_cat and matches_query:
            filtered.append(item)
    return filtered


def get_stock_item_by_id(db: Session, item_id: int) -> StockItem | None:
    """Retrieve a single stock item by primary key."""
    return db.get(StockItem, item_id)


def create_stock_item(
    db: Session,
    name: str,
    category: str,
    quantity: int,
    unit: str,
    min_quantity: int,
    image_filename: str | None = None,
) -> StockItem:
    """Create a new supply item in NGO inventory."""
    qty = max(0, quantity)
    min_qty = max(0, min_quantity)
    status = "Estoque Critico" if qty <= min_qty else "Normal"
    item = StockItem(
        name=name.strip(),
        category=category.strip(),
        quantity=qty,
        unit=unit.strip() or "un",
        lot_number="—",
        expiration_date="—",
        min_quantity=min_qty,
        status=status,
        image_filename=image_filename,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def register_stock_movement(
    db: Session,
    item_id: int,
    movement_type: str,
    quantity: int,
) -> StockItem | None:
    """Apply an entry or exit movement to a stock item and recalculate status."""
    item = db.get(StockItem, item_id)
    if item is None:
        return None

    delta = abs(quantity)
    if _fold(movement_type).startswith("saida"):
        item.quantity = max(0, item.quantity - delta)
    else:
        item.quantity += delta

    if item.quantity <= item.min_quantity:
        item.status = "Estoque Critico"
    elif item.status == "Estoque Critico":
        item.status = "Normal"

    db.commit()
    db.refresh(item)
    return item


# ---------------------------------------------------------------------------
# Foster Homes & Adoptions
# ---------------------------------------------------------------------------


def list_temporary_homes(db: Session) -> list[TemporaryHome]:
    """List registered volunteer foster homes."""
    return list(
        db.scalars(select(TemporaryHome).order_by(TemporaryHome.id.asc())).all()
    )


def get_temporary_home_by_id(db: Session, home_id: int) -> TemporaryHome | None:
    """Retrieve a single volunteer foster home by ID."""
    return db.get(TemporaryHome, home_id)


def create_temporary_home(
    db: Session,
    volunteer_name: str,
    contact: str,
    neighborhood: str,
    capacity: int,
) -> TemporaryHome:
    """Register a new volunteer foster home."""
    home = TemporaryHome(
        volunteer_name=volunteer_name.strip(),
        contact=contact.strip(),
        neighborhood=neighborhood.strip(),
        capacity=max(1, capacity),
        active_animals_csv="",
    )
    db.add(home)
    db.commit()
    db.refresh(home)
    return home


def update_temporary_home(
    db: Session,
    home_id: int,
    volunteer_name: str,
    contact: str,
    neighborhood: str,
    capacity: int,
) -> TemporaryHome | None:
    """Update an existing volunteer foster home."""
    home = db.get(TemporaryHome, home_id)
    if home is None:
        return None
    home.volunteer_name = volunteer_name.strip()
    home.contact = contact.strip()
    home.neighborhood = neighborhood.strip()
    home.capacity = max(1, capacity)
    db.commit()
    db.refresh(home)
    return home


def delete_temporary_home(db: Session, home_id: int) -> bool:
    """Delete a volunteer foster home by ID."""
    home = db.get(TemporaryHome, home_id)
    if home is None:
        return False
    db.delete(home)
    db.commit()
    return True


def list_adoptions(db: Session) -> list[AdoptionTerm]:
    """List recorded adoptions."""
    return list(db.scalars(select(AdoptionTerm).order_by(AdoptionTerm.id.desc())).all())


def get_adoption_by_id(db: Session, adoption_id: int) -> AdoptionTerm | None:
    """Retrieve a single adoption record by ID."""
    return db.get(AdoptionTerm, adoption_id)


def update_adoption_record(
    db: Session,
    adoption_id: int,
    adopter_name: str,
    adopter_cpf: str,
    adopter_contact: str,
    adopter_address: str,
    adoption_date: str,
) -> AdoptionTerm | None:
    """Update an existing adoption record."""
    term = db.get(AdoptionTerm, adoption_id)
    if term is None:
        return None
    term.adopter_name = adopter_name.strip()
    term.adopter_cpf = adopter_cpf.strip()
    term.adopter_contact = adopter_contact.strip()
    term.adopter_address = adopter_address.strip()
    if adoption_date.strip():
        term.adoption_date = adoption_date.strip()
    db.commit()
    db.refresh(term)
    return term


def delete_adoption_record(db: Session, adoption_id: int) -> bool:
    """Delete an adoption record by ID."""
    term = db.get(AdoptionTerm, adoption_id)
    if term is None:
        return False
    db.delete(term)
    db.commit()
    return True


def create_adoption_record(
    db: Session,
    animal_id: int,
    adopter_name: str,
    adopter_cpf: str,
    adopter_contact: str,
    adopter_address: str,
    adoption_date: str,
) -> AdoptionTerm | None:
    """Register an adoption and mark the animal as Adopted."""
    animal = db.get(Animal, animal_id)
    if animal is None:
        return None
    term = AdoptionTerm(
        adopter_name=adopter_name.strip(),
        adopter_cpf=adopter_cpf.strip(),
        adopter_contact=adopter_contact.strip(),
        adopter_address=adopter_address.strip(),
        animal_name=animal.name,
        animal_species=animal.species,
        adoption_date=adoption_date,
        status="Concluida",
    )
    animal.status = "Adotado"
    animal.location = f"Adotado - {adopter_name.strip()}"
    db.add(term)
    db.commit()
    db.refresh(term)
    return term


# ---------------------------------------------------------------------------
# Financial Module
# ---------------------------------------------------------------------------


def list_financial_transactions(
    db: Session,
    tx_type: str = "",
    category: str = "",
) -> list[FinancialTransaction]:
    """List financial transactions with optional type and category filters."""
    stmt = select(FinancialTransaction).order_by(FinancialTransaction.id.desc())
    items = list(db.scalars(stmt).all())
    t_filter = _fold(tx_type)
    c_filter = _fold(category)

    return [
        tx
        for tx in items
        if (not t_filter or _fold(tx.tx_type) == t_filter)
        and (not c_filter or _fold(tx.category) == c_filter)
    ]


def calculate_financial_summary(
    transactions: list[FinancialTransaction],
) -> FinancialSummary:
    """Compute total income, paid expenses, pending expenses, and net balance."""
    income = sum(
        tx.amount_cents
        for tx in transactions
        if tx.tx_type == "Entrada" and tx.status == "Pago"
    )
    expense = sum(
        tx.amount_cents
        for tx in transactions
        if tx.tx_type == "Saida" and tx.status == "Pago"
    )
    pending = sum(
        tx.amount_cents
        for tx in transactions
        if tx.tx_type == "Saida" and tx.status == "Pendente"
    )
    return FinancialSummary(
        total_income_cents=income,
        total_expense_cents=expense,
        pending_expense_cents=pending,
        balance_cents=income - expense,
    )


def create_financial_transaction(
    db: Session,
    tx: FinancialTransaction,
) -> FinancialTransaction:
    """Persist a new financial transaction."""
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


def mark_transaction_paid(db: Session, tx_id: int) -> FinancialTransaction | None:
    """Mark a pending financial transaction as paid."""
    tx = db.get(FinancialTransaction, tx_id)
    if tx is None:
        return None
    tx.status = "Pago"
    db.commit()
    db.refresh(tx)
    return tx


# ---------------------------------------------------------------------------
# Idempotent Initial Seed
# ---------------------------------------------------------------------------


def seed_initial_data(db: Session) -> None:
    """Populate initial NGO data if the database is empty."""
    if db.scalar(select(Usuario.id).limit(1)) is None:
        db.add_all(
            [
                Usuario(
                    nome="Coordenacao Patas e Pelos",
                    email="coordenacao@patasepelos.org.br",
                    senha_hash=hash_password("prototipo2026"),
                    role="admin",
                    ativo=True,
                ),
                Usuario(
                    nome="Lucia Schmidt",
                    email="lucia.voluntaria@patasepelos.org.br",
                    senha_hash=hash_password("voluntario2026"),
                    role="voluntario",
                    ativo=True,
                ),
            ]
        )
        db.commit()

    if db.scalar(select(Animal.id).limit(1)) is None:
        _seed_animals(db)

    if db.scalar(select(StockItem.id).limit(1)) is None:
        _seed_stock(db)

    if db.scalar(select(TemporaryHome.id).limit(1)) is None:
        _seed_foster_and_adoptions(db)

    if db.scalar(select(FinancialTransaction.id).limit(1)) is None:
        _seed_financial(db)


def _seed_animals(db: Session) -> None:
    """Insert initial animals, vaccines, and clinical records."""
    pipoca = Animal(
        name="Pipoca",
        species="Canina",
        breed="Sem Raça Definida",
        size="Médio (14 kg)",
        age_approx="2 anos",
        gender="Fêmea",
        status="Em Tratamento",
        intake_date="12/08/2026",
        neutered=True,
        location="Clínica Veterinária Parceira",
        microchip="90011800294101",
        rescue_notes=(
            "Resgatada com fratura na pata traseira direita no Bairro Bela Uniao."
        ),
        temperament="Carinhosa e tranquila, em recuperacao ortopedica.",
        foster_history_text=(
            "12/08/2026 - Atual: Internacao e recuperacao na Clinica Parceira."
        ),
        vaccines=[
            VaccineRecord(
                name="Vacina V10",
                date_applied="15/08/2026",
                next_due_date="15/08/2027",
                lot="V10-8842",
                record_type="Vacina",
                status="Em dia",
            ),
            VaccineRecord(
                name="Antirrabica",
                date_applied="15/08/2026",
                next_due_date="15/08/2027",
                lot="RAB-2026-X",
                record_type="Vacina",
                status="Em dia",
            ),
            VaccineRecord(
                name="Drontal Plus 10kg",
                date_applied="20/08/2026",
                next_due_date="20/11/2026",
                lot="DRT-5521",
                record_type="Vermifugo",
                status="Reforco proximo",
            ),
        ],
        clinical_events=[
            ClinicalEvent(
                date="12/08/2026",
                title="Triagem inicial de resgate",
                category="Triagem",
                veterinarian="Dra. Camila Ferreira (CRMV-RS 14820)",
                notes="Radiografia confirmou fratura fechada em femur direito.",
            ),
            ClinicalEvent(
                date="18/08/2026",
                title="Osteossintese de femur direito",
                category="Cirurgia",
                veterinarian="Dr. Rafael Bastos (CRMV-RS 11904)",
                notes="Procedimento concluido sem intercorrencias.",
            ),
            ClinicalEvent(
                date="24/09/2026",
                title="Reavaliacao pos-operatoria ortopedica",
                category="Consulta",
                veterinarian="Dra. Camila Ferreira (CRMV-RS 14820)",
                notes="Cicatrizacao adequada. Manter Meloxicam 2mg por 6 dias.",
            ),
        ],
    )

    thor = Animal(
        name="Thor",
        species="Canina",
        breed="Mix Labrador",
        size="Grande (28 kg)",
        age_approx="3 anos",
        gender="Macho",
        status="Lar Temporario",
        intake_date="05/06/2026",
        neutered=True,
        location="Lar Temporario - Casa da Voluntaria Lucia",
        microchip="90011800294102",
        rescue_notes=(
            "Encontrado abandonado na ERS-342. Extremamente docil com criancas."
        ),
        temperament="Muito docil, brincalhao e sociavel com criancas e caes.",
        foster_history_text=(
            "15/06/2026 - Atual: Lar Temporario de Lucia Schmidt (Centro).\n"
            "05/06/2026 - 15/06/2026: Quarentena na Sede Canil Central."
        ),
        vaccines=[
            VaccineRecord(
                name="Vacina V10",
                date_applied="10/06/2026",
                next_due_date="10/10/2026",
                lot="V10-7711",
                record_type="Vacina",
                status="Pendente",
            ),
        ],
        clinical_events=[
            ClinicalEvent(
                date="22/07/2026",
                title="Alta dermatologica",
                category="Consulta",
                veterinarian="Dra. Camila Ferreira (CRMV-RS 14820)",
                notes="Pele totalmente recuperada apos protocolo com Simparic.",
            ),
        ],
    )

    mel = Animal(
        name="Mel",
        species="Felina",
        breed="Siames Mestico",
        size="Pequeno (3,1 kg)",
        age_approx="8 meses",
        gender="Femea",
        status="Acolhido",
        intake_date="20/09/2026",
        neutered=False,
        location="Gatil Central - Modulo B",
        microchip="90011800294103",
        rescue_notes="Ninhada resgatada em terreno baldio. Castracao agendada.",
        temperament="Curiosa, calma e adaptada a caixa de areia.",
        foster_history_text="20/09/2026 - Atual: Gatil Central - Modulo B.",
        vaccines=[
            VaccineRecord(
                name="Vacina Felina V4",
                date_applied="21/09/2026",
                next_due_date="21/10/2026",
                lot="FEL-4091",
                record_type="Vacina",
                status="Pendente",
            ),
        ],
        clinical_events=[
            ClinicalEvent(
                date="21/09/2026",
                title="Testagem FIV/FeLV e primeira dose V4",
                category="Exame",
                veterinarian="Dra. Camila Ferreira (CRMV-RS 14820)",
                notes="Resultado negativo para retroviroses.",
            ),
        ],
    )

    barao = Animal(
        name="Barao",
        species="Canina",
        breed="Pastor Alemao Mestico",
        size="Grande (32 kg)",
        age_approx="5 anos",
        gender="Macho",
        status="Disponivel para Adocao",
        intake_date="14/03/2026",
        neutered=True,
        location="Canil Central - Baia 1",
        microchip="90011800294104",
        rescue_notes=("Resgate em situacao de maus-tratos. Plenamente recuperado."),
        temperament="Protetor, equilibrado e ideal para patio amplo e cercado.",
        foster_history_text="14/03/2026 - Atual: Canil Central - Baia 1.",
        vaccines=[
            VaccineRecord(
                name="Vacina V10",
                date_applied="20/03/2026",
                next_due_date="20/03/2027",
                lot="V10-6540",
                record_type="Vacina",
                status="Em dia",
            ),
            VaccineRecord(
                name="Antirrabica",
                date_applied="20/03/2026",
                next_due_date="20/03/2027",
                lot="RAB-2026-X",
                record_type="Vacina",
                status="Em dia",
            ),
        ],
        clinical_events=[
            ClinicalEvent(
                date="12/05/2026",
                title="Liberacao clinica para adocao",
                category="Consulta",
                veterinarian="Dra. Camila Ferreira (CRMV-RS 14820)",
                notes="Protocolo vacinal completo e comportamento estavel.",
            ),
        ],
    )

    luna = Animal(
        name="Luna",
        species="Felina",
        breed="Frajola",
        size="Pequeno (3,8 kg)",
        age_approx="1 ano",
        gender="Fêmea",
        status="Adotado",
        intake_date="10/05/2026",
        neutered=True,
        location="Adotada - Familia Souza",
        microchip="90011800294105",
        rescue_notes="Adocao concluida em setembro. Pos-adocao ativo.",
        temperament="Docial e apegada a pessoas.",
        foster_history_text=(
            "15/09/2026 - Atual: Adotada por Ana Paula de Souza.\n"
            "10/05/2026 - 15/09/2026: Gatil Central - Modulo A."
        ),
        vaccines=[
            VaccineRecord(
                name="Vacina Felina V4",
                date_applied="15/05/2026",
                next_due_date="15/05/2027",
                lot="FEL-3312",
                record_type="Vacina",
                status="Em dia",
            ),
        ],
        clinical_events=[
            ClinicalEvent(
                date="15/09/2026",
                title="Check-up pre-adocao",
                category="Consulta",
                veterinarian="Dra. Camila Ferreira (CRMV-RS 14820)",
                notes="Animal saudavel, entregue com carteirinha atualizada.",
            ),
        ],
    )

    amora = Animal(
        name="Amora",
        species="Felina",
        breed="Tigrada",
        size="Pequeno (3,4 kg)",
        age_approx="1 ano e 4 meses",
        gender="Fêmea",
        status="Disponível para Adoção",
        intake_date="02/07/2026",
        neutered=True,
        location="Gatil Central - Modulo A",
        microchip="90011800294106",
        rescue_notes="Resgatada filhote perto da rodoviaria. Saudavel e castrada.",
        temperament="Muito carinhosa, se da bem com outros gatos e apartamento.",
        foster_history_text="02/07/2026 - Atual: Gatil Central - Modulo A.",
        vaccines=[
            VaccineRecord(
                name="Vacina Felina V4",
                date_applied="10/07/2026",
                next_due_date="10/07/2027",
                lot="FEL-3902",
                record_type="Vacina",
                status="Em dia",
            ),
        ],
        clinical_events=[
            ClinicalEvent(
                date="01/08/2026",
                title="Castracao e liberacao para adocao",
                category="Cirurgia",
                veterinarian="Dra. Camila Ferreira (CRMV-RS 14820)",
                notes="FIV/FeLV negativo, pronta para adocao responsavel.",
            ),
        ],
    )

    db.add_all([pipoca, thor, mel, barao, luna, amora])
    db.commit()


def _seed_stock(db: Session) -> None:
    """Insert initial NGO supplies (food, litter, hygiene, and accessories)."""
    db.add_all(
        [
            StockItem(
                name="Racao Seca Caes Adultos (Saco 15kg)",
                category="Racao",
                quantity=12,
                unit="sacos",
                lot_number="RC-AD-15",
                expiration_date="05/03/2027",
                min_quantity=6,
                status="Normal",
            ),
            StockItem(
                name="Racao Seca Caes Filhotes (Saco 10kg)",
                category="Racao",
                quantity=2,
                unit="sacos",
                lot_number="RC-FL-10",
                expiration_date="10/12/2026",
                min_quantity=4,
                status="Estoque Critico",
            ),
            StockItem(
                name="Racao Gatos Castrados (Saco 10kg)",
                category="Racao",
                quantity=5,
                unit="sacos",
                lot_number="RC-GT-10",
                expiration_date="20/04/2027",
                min_quantity=3,
                status="Normal",
            ),
            StockItem(
                name="Areia Sanitaria para Gatos (4kg)",
                category="Higiene",
                quantity=3,
                unit="pacotes",
                lot_number="AR-04",
                expiration_date="—",
                min_quantity=5,
                status="Estoque Critico",
            ),
            StockItem(
                name="Tapete Higienico Descartavel (30 un)",
                category="Higiene",
                quantity=8,
                unit="pacotes",
                lot_number="TP-30",
                expiration_date="—",
                min_quantity=4,
                status="Normal",
            ),
            StockItem(
                name="Coleiras e Guias Sortidas",
                category="Acessorios",
                quantity=14,
                unit="unidades",
                lot_number="AC-01",
                expiration_date="—",
                min_quantity=5,
                status="Normal",
            ),
        ]
    )
    db.commit()


def _seed_foster_and_adoptions(db: Session) -> None:
    """Insert initial temporary homes and completed adoption terms."""
    db.add_all(
        [
            TemporaryHome(
                volunteer_name="Lucia Schmidt",
                contact="(55) 99611-2233",
                neighborhood="Centro",
                capacity=2,
                active_animals_csv="Thor",
            ),
            TemporaryHome(
                volunteer_name="Carlos Eduardo Silveira",
                contact="(55) 98144-5566",
                neighborhood="Vila Campina",
                capacity=3,
                active_animals_csv="",
            ),
            TemporaryHome(
                volunteer_name="Mariana Weber",
                contact="(55) 99922-7788",
                neighborhood="Bela Uniao",
                capacity=1,
                active_animals_csv="",
            ),
        ]
    )
    db.add(
        AdoptionTerm(
            adopter_name="Ana Paula de Souza",
            adopter_cpf="987.654.321-00",
            adopter_contact="(55) 99188-4455",
            adopter_address="Rua Uruguai, 450 - Horizontina/RS",
            animal_name="Luna",
            animal_species="Felina",
            adoption_date="15/09/2026",
            status="Concluida",
        )
    )
    db.commit()


def _seed_financial(db: Session) -> None:
    """Insert initial realistic NGO financial transactions."""
    db.add_all(
        [
            FinancialTransaction(
                tx_date="05/09/2026",
                tx_type="Entrada",
                category="Doacao PIX",
                description="Campanha mensal de padrinhos (18 apoiadores)",
                amount_cents=145000,
                payment_method="PIX",
                status="Pago",
                related_animal=None,
                created_by="coordenacao@patasepelos.org.br",
            ),
            FinancialTransaction(
                tx_date="12/09/2026",
                tx_type="Entrada",
                category="Rifa / Brecho",
                description="Brecho solidario na Praca 25 de Julho",
                amount_cents=82000,
                payment_method="Dinheiro",
                status="Pago",
                related_animal=None,
                created_by="coordenacao@patasepelos.org.br",
            ),
            FinancialTransaction(
                tx_date="16/09/2026",
                tx_type="Saida",
                category="Racao",
                description="Compra de 180kg Racao Adulto Premium (Lote RC-20260901)",
                amount_cents=96000,
                payment_method="Transferencia",
                status="Pago",
                related_animal=None,
                created_by="coordenacao@patasepelos.org.br",
            ),
            FinancialTransaction(
                tx_date="20/09/2026",
                tx_type="Saida",
                category="Clinica Veterinaria",
                description=(
                    "Fatura cirurgia ortopedica e internacao - Clinica Parceira"
                ),
                amount_cents=68000,
                payment_method="PIX",
                status="Pendente",
                related_animal="Pipoca",
                created_by="coordenacao@patasepelos.org.br",
            ),
            FinancialTransaction(
                tx_date="22/09/2026",
                tx_type="Saida",
                category="Medicamentos",
                description="Reposicao de vacinas V4 e antibioticos",
                amount_cents=31500,
                payment_method="PIX",
                status="Pago",
                related_animal="Mel",
                created_by="lucia.voluntaria@patasepelos.org.br",
            ),
        ]
    )
    db.commit()
