"""Relational data models for the Canis system using SQLAlchemy 2.0."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all Canis database models."""

    pass


class Usuario(Base):
    """Authenticated volunteer or administrator of ONG Patas e Pelos."""

    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    senha_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_sub: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tema: Mapped[str] = mapped_column(String(20), default="dark")
    role: Mapped[str] = mapped_column(String(30), default="pendente", index=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Animal(Base):
    """Rescued animal managed by the NGO."""

    __tablename__ = "animais"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    species: Mapped[str] = mapped_column(String(40), index=True)
    breed: Mapped[str] = mapped_column(String(120))
    size: Mapped[str] = mapped_column(String(60), default="Medio")
    age_approx: Mapped[str] = mapped_column(String(60))
    gender: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(60), index=True)
    intake_date: Mapped[str] = mapped_column(String(20))
    neutered: Mapped[bool] = mapped_column(Boolean, default=False)
    location: Mapped[str] = mapped_column(String(200))
    microchip: Mapped[str] = mapped_column(String(60), default="", index=True)
    rescue_notes: Mapped[str] = mapped_column(Text, default="")
    temperament: Mapped[str] = mapped_column(String(255), default="")
    foster_history_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    vaccines: Mapped[list["VaccineRecord"]] = relationship(
        "VaccineRecord",
        back_populates="animal",
        cascade="all, delete-orphan",
        order_by="VaccineRecord.id.desc()",
    )
    clinical_events: Mapped[list["ClinicalEvent"]] = relationship(
        "ClinicalEvent",
        back_populates="animal",
        cascade="all, delete-orphan",
        order_by="ClinicalEvent.id.desc()",
    )
    photos: Mapped[list["AnimalPhoto"]] = relationship(
        "AnimalPhoto",
        back_populates="animal",
        cascade="all, delete-orphan",
        order_by="AnimalPhoto.is_primary.desc(), AnimalPhoto.id.asc()",
    )

    @property
    def primary_photo_id(self) -> int | None:
        """Return the ID of the primary photo (or first available photo)."""
        if not self.photos:
            return None
        for photo in self.photos:
            if photo.is_primary:
                return photo.id
        return self.photos[0].id

    @property
    def foster_history(self) -> list[str]:
        """Return foster history lines as a list of strings."""
        if not self.foster_history_text:
            return [f"{self.intake_date} - Atual: {self.location}"]
        return [
            line.strip()
            for line in self.foster_history_text.splitlines()
            if line.strip()
        ]

    @property
    def size_category(self) -> str:
        """Return normalized size bucket ('Pequeno', 'Medio', or 'Grande')."""
        lower = self.size.lower()
        if "pequeno" in lower:
            return "Pequeno"
        if "grande" in lower:
            return "Grande"
        return "Medio"


class VaccineRecord(Base):
    """Vaccine or dewormer application record linked to an animal."""

    __tablename__ = "vacinas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    animal_id: Mapped[int] = mapped_column(
        ForeignKey("animais.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    date_applied: Mapped[str] = mapped_column(String(20))
    next_due_date: Mapped[str] = mapped_column(String(20))
    lot: Mapped[str] = mapped_column(String(60))
    record_type: Mapped[str] = mapped_column(String(40), default="Vacina")
    status: Mapped[str] = mapped_column(String(40), default="Em dia")

    animal: Mapped["Animal"] = relationship("Animal", back_populates="vaccines")


class ClinicalEvent(Base):
    """Chronological clinical consultation, surgery, or medication event."""

    __tablename__ = "eventos_clinicos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    animal_id: Mapped[int] = mapped_column(
        ForeignKey("animais.id", ondelete="CASCADE"), index=True
    )
    date: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(180))
    category: Mapped[str] = mapped_column(String(60))
    veterinarian: Mapped[str] = mapped_column(String(150))
    notes: Mapped[str] = mapped_column(Text)

    animal: Mapped["Animal"] = relationship("Animal", back_populates="clinical_events")


class AnimalPhoto(Base):
    """Downscaled photo attached to an animal."""

    __tablename__ = "animal_fotos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    animal_id: Mapped[int] = mapped_column(
        ForeignKey("animais.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    animal: Mapped["Animal"] = relationship("Animal", back_populates="photos")


class StockItem(Base):
    """Pharmaceutical, hygiene, or food supply lot in NGO inventory."""

    __tablename__ = "itens_estoque"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    category: Mapped[str] = mapped_column(String(60), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str] = mapped_column(String(40))
    lot_number: Mapped[str] = mapped_column(String(60), index=True)
    expiration_date: Mapped[str] = mapped_column(String(20))
    min_quantity: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(40), default="Normal")
    image_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)


class TemporaryHome(Base):
    """Registered volunteer foster home."""

    __tablename__ = "lares_temporarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    volunteer_name: Mapped[str] = mapped_column(String(150))
    contact: Mapped[str] = mapped_column(String(60))
    neighborhood: Mapped[str] = mapped_column(String(120))
    capacity: Mapped[int] = mapped_column(Integer, default=1)
    active_animals_csv: Mapped[str] = mapped_column(String(255), default="")

    @property
    def active_animals(self) -> list[str]:
        """Return active animal names currently hosted in this foster home."""
        if not self.active_animals_csv:
            return []
        return [
            item.strip() for item in self.active_animals_csv.split(",") if item.strip()
        ]


class AdoptionTerm(Base):
    """Completed adoption agreement record."""

    __tablename__ = "termos_adocao"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    adopter_name: Mapped[str] = mapped_column(String(180))
    adopter_cpf: Mapped[str] = mapped_column(String(20))
    adopter_contact: Mapped[str] = mapped_column(String(60))
    adopter_address: Mapped[str] = mapped_column(String(255))
    animal_name: Mapped[str] = mapped_column(String(120))
    animal_species: Mapped[str] = mapped_column(String(40))
    adoption_date: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(40), default="Concluida")


class FinancialTransaction(Base):
    """NGO financial entry representing donations, campaigns, or veterinary expenses."""

    __tablename__ = "lancamentos_financeiros"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tx_date: Mapped[str] = mapped_column(String(20))
    tx_type: Mapped[str] = mapped_column(String(20), index=True)
    category: Mapped[str] = mapped_column(String(60), index=True)
    description: Mapped[str] = mapped_column(String(255))
    amount_cents: Mapped[int] = mapped_column(Integer)
    payment_method: Mapped[str] = mapped_column(String(40), default="PIX")
    status: Mapped[str] = mapped_column(String(20), default="Pago", index=True)
    related_animal: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def amount_brl(self) -> str:
        """Format amount_cents in Brazilian Real notation (e.g. 'R$ 1.250,00')."""
        reais = self.amount_cents / 100
        formatted = (
            f"{reais:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        )
        return f"R$ {formatted}"
