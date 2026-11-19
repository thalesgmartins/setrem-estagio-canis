"""Mock data repository for the Canis system prototype."""

from dataclasses import dataclass, field


@dataclass
class VaccineRecord:
    """Represents a vaccine record of an animal."""

    name: str
    date_applied: str
    next_due_date: str
    lot: str


@dataclass
class Animal:
    """Represents an animal under the care of the NGO."""

    id: int
    name: str
    species: str
    breed: str
    age_approx: str
    gender: str
    status: str
    intake_date: str
    neutered: bool
    location: str
    rescue_notes: str
    vaccines: list[VaccineRecord] = field(default_factory=list)
    medical_notes: list[str] = field(default_factory=list)


@dataclass
class StockItem:
    """Represents a pharmaceutical or food supply item."""

    id: int
    name: str
    category: str
    quantity: int
    unit: str
    lot_number: str
    expiration_date: str
    min_quantity: int
    status: str


@dataclass
class TemporaryHome:
    """Represents a registered volunteer foster home."""

    id: int
    volunteer_name: str
    contact: str
    neighborhood: str
    capacity: int
    active_animals: list[str]


@dataclass
class AdoptionTerm:
    """Represents an adoption term."""

    id: int
    adopter_name: str
    adopter_cpf: str
    adopter_contact: str
    adopter_address: str
    animal_name: str
    animal_species: str
    adoption_date: str
    status: str


def get_mock_animals() -> list[Animal]:
    """Retrieve sample list of rescued animals.

    Returns:
        List of Animal instances representing typical NGO records.
    """
    return [
        Animal(
            id=1,
            name="Pipoca",
            species="Canina",
            breed="Sem Raca Definida (SRD)",
            age_approx="2 anos",
            gender="Femea",
            status="Em Tratamento",
            intake_date="12/08/2026",
            neutered=True,
            location="Clinica Veterinaria Parceira",
            rescue_notes=(
                "Resgatada com fratura na pata traseira direita no Bairro Bela Uniao."
            ),
            vaccines=[
                VaccineRecord(
                    name="Vacina V10",
                    date_applied="15/08/2026",
                    next_due_date="15/08/2027",
                    lot="V10-8842",
                ),
                VaccineRecord(
                    name="Antirrabica",
                    date_applied="15/08/2026",
                    next_due_date="15/08/2027",
                    lot="RAB-2026-X",
                ),
            ],
            medical_notes=[
                "Cirurgia ortopedica realizada com sucesso em 18/08.",
                "Em administracao de anti-inflamatorio ate 30/09.",
            ],
        ),
        Animal(
            id=2,
            name="Thor",
            species="Canina",
            breed="Mix Labrador",
            age_approx="3 anos",
            gender="Macho",
            status="Lar Temporario",
            intake_date="05/06/2026",
            neutered=True,
            location="Lar Temporario - Casa da Voluntaria Lucia",
            rescue_notes=(
                "Encontrado abandonado na ERS-342. Extremamente docil com criancas."
            ),
            vaccines=[
                VaccineRecord(
                    name="Vacina V10",
                    date_applied="10/06/2026",
                    next_due_date="10/10/2026",
                    lot="V10-7711",
                ),
            ],
            medical_notes=[
                "Tratamento de dermatite finalizado em julho.",
                "Reforco de vacina agendado para outubro.",
            ],
        ),
        Animal(
            id=3,
            name="Mel",
            species="Felina",
            breed="Siamês Mestiço",
            age_approx="8 meses",
            gender="Femea",
            status="Acolhido",
            intake_date="20/09/2026",
            neutered=False,
            location="Gatil Central - Modulo B",
            rescue_notes="Ninhada resgatada em terreno baldio. Castracao agendada.",
            vaccines=[
                VaccineRecord(
                    name="Vacina Felina V4",
                    date_applied="21/09/2026",
                    next_due_date="21/10/2026",
                    lot="FEL-4091",
                ),
            ],
            medical_notes=[
                "FIV/FeLV Negativo em teste rapido.",
                "Castracao programada para 10/10.",
            ],
        ),
        Animal(
            id=4,
            name="Barão",
            species="Canina",
            breed="Pastor Alemao Mestiço",
            age_approx="5 anos",
            gender="Macho",
            status="Disponivel para Adocao",
            intake_date="14/03/2026",
            neutered=True,
            location="Canil Central - Baia 1",
            rescue_notes=(
                "Resgate em situacao de maus-tratos. Plenamente recuperado "
                "e sociabilizado."
            ),
            vaccines=[
                VaccineRecord(
                    name="Vacina V10",
                    date_applied="20/03/2026",
                    next_due_date="20/03/2027",
                    lot="V10-6540",
                ),
                VaccineRecord(
                    name="Antirrabica",
                    date_applied="20/03/2026",
                    next_due_date="20/03/2027",
                    lot="RAB-2026-X",
                ),
            ],
            medical_notes=[
                "Apto para adocao responsável.",
                "Necessita de espaco amplo.",
            ],
        ),
        Animal(
            id=5,
            name="Luna",
            species="Felina",
            breed="Frajola (SRD)",
            age_approx="1 ano",
            gender="Femea",
            status="Adotado",
            intake_date="10/05/2026",
            neutered=True,
            location="Adotada - Familia Souza",
            rescue_notes=(
                "Adocao concluida em setembro. Acompanhamento pos-adocao ativo."
            ),
            vaccines=[
                VaccineRecord(
                    name="Vacina Felina V4",
                    date_applied="15/05/2026",
                    next_due_date="15/05/2027",
                    lot="FEL-3312",
                ),
            ],
            medical_notes=[
                "Termo de adocao assinado com sucesso.",
            ],
        ),
    ]


def get_mock_stock() -> list[StockItem]:
    """Retrieve sample list of supplies and medicines.

    Returns:
        List of StockItem instances.
    """
    return [
        StockItem(
            id=1,
            name="Vacina Canina Nobivac Puppy DP",
            category="Vacina",
            quantity=8,
            unit="doses",
            lot_number="NV-2026-09",
            expiration_date="15/10/2026",
            min_quantity=10,
            status="Vencendo em breve",
        ),
        StockItem(
            id=2,
            name="Amoxicilina + Clavulanato 250mg",
            category="Antibiotico",
            quantity=3,
            unit="frascos",
            lot_number="AMX-7412",
            expiration_date="10/12/2026",
            min_quantity=5,
            status="Estoque Critico",
        ),
        StockItem(
            id=3,
            name="Simparic 20 a 40kg",
            category="Antiparasitario",
            quantity=14,
            unit="comprimidos",
            lot_number="SIM-9910",
            expiration_date="30/08/2027",
            min_quantity=6,
            status="Normal",
        ),
        StockItem(
            id=4,
            name="Racao Seca Adulto Premium Especial",
            category="Racao",
            quantity=180,
            unit="kg",
            lot_number="RC-20260901",
            expiration_date="05/03/2027",
            min_quantity=80,
            status="Normal",
        ),
        StockItem(
            id=5,
            name="Meloxicam 2mg Comprimidos",
            category="Anti-inflamatorio",
            quantity=2,
            unit="caixas",
            lot_number="MLX-4501",
            expiration_date="20/11/2026",
            min_quantity=4,
            status="Estoque Critico",
        ),
    ]


def get_mock_temporary_homes() -> list[TemporaryHome]:
    """Retrieve registered foster homes.

    Returns:
        List of TemporaryHome instances.
    """
    return [
        TemporaryHome(
            id=1,
            volunteer_name="Lucia Schmidt",
            contact="(55) 99611-2233",
            neighborhood="Centro",
            capacity=2,
            active_animals=["Thor"],
        ),
        TemporaryHome(
            id=2,
            volunteer_name="Carlos Eduardo Silveira",
            contact="(55) 98144-5566",
            neighborhood="Vila Campina",
            capacity=3,
            active_animals=[],
        ),
        TemporaryHome(
            id=3,
            volunteer_name="Mariana Weber",
            contact="(55) 99922-7788",
            neighborhood="Bela Uniao",
            capacity=1,
            active_animals=[],
        ),
    ]


def get_mock_adoptions() -> list[AdoptionTerm]:
    """Retrieve sample adoption records.

    Returns:
        List of AdoptionTerm instances.
    """
    return [
        AdoptionTerm(
            id=1,
            adopter_name="Ana Paula de Souza",
            adopter_cpf="987.654.321-00",
            adopter_contact="(55) 99188-4455",
            adopter_address="Rua Uruguai, 450 - Horizontina/RS",
            animal_name="Luna",
            animal_species="Felina",
            adoption_date="15/09/2026",
            status="Concluida",
        ),
    ]
