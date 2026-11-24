"""Mock data repository for the Canis system prototype."""

from dataclasses import dataclass, field


@dataclass
class VaccineRecord:
    """Represents a vaccine or dewormer record of an animal."""

    name: str
    date_applied: str
    next_due_date: str
    lot: str
    record_type: str = "Vacina"
    status: str = "Em dia"


@dataclass
class ClinicalEvent:
    """Represents a chronological clinical consultation, surgery, or medication."""

    date: str
    title: str
    category: str
    veterinarian: str
    notes: str


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
    size: str = "Medio"
    microchip: str = ""
    vaccines: list[VaccineRecord] = field(default_factory=list)
    medical_notes: list[str] = field(default_factory=list)
    clinical_events: list[ClinicalEvent] = field(default_factory=list)
    foster_history: list[str] = field(default_factory=list)


@dataclass
class StockItem:
    """Represents a pharmaceutical, hygiene, or food supply item."""

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


@dataclass
class OperationalAlert:
    """Represents a priority operational alert shown on the dashboard."""

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
    """Represents a recent operational event in the ONG feed."""

    timestamp: str
    category: str
    title: str
    detail: str
    action_label: str
    action_url: str
    use_htmx: bool = False


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
            size="Medio (14 kg)",
            microchip="90011800294101",
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
            medical_notes=[
                "Cirurgia ortopedica realizada com sucesso em 18/08.",
                "Em administracao de anti-inflamatorio ate 30/09.",
            ],
            clinical_events=[
                ClinicalEvent(
                    date="24/09/2026",
                    title="Reavaliacao pos-operatoria ortopedica",
                    category="Consulta",
                    veterinarian="Dra. Camila Ferreira (CRMV-RS 14820)",
                    notes=(
                        "Cicatrizacao adequada. Manter Meloxicam 2mg por mais "
                        "6 dias e fisioterapia leve."
                    ),
                ),
                ClinicalEvent(
                    date="18/08/2026",
                    title="Osteossintese de femur direito",
                    category="Cirurgia",
                    veterinarian="Dr. Rafael Bastos (CRMV-RS 11904)",
                    notes=(
                        "Procedimento concluido sem intercorrencias. Prescrito "
                        "Amoxicilina + Clavulanato 250mg por 10 dias."
                    ),
                ),
                ClinicalEvent(
                    date="12/08/2026",
                    title="Triagem inicial de resgate",
                    category="Triagem",
                    veterinarian="Dra. Camila Ferreira (CRMV-RS 14820)",
                    notes=(
                        "Animal hidratado, exame de hemograma dentro da "
                        "normalidade, radiografia confirmou fratura fechada."
                    ),
                ),
            ],
            foster_history=[
                "12/08/2026 - Atual: Internacao e recuperacao na Clinica Parceira.",
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
            size="Grande (28 kg)",
            microchip="90011800294102",
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
            medical_notes=[
                "Tratamento de dermatite finalizado em julho.",
                "Reforco de vacina agendado para outubro.",
            ],
            clinical_events=[
                ClinicalEvent(
                    date="22/07/2026",
                    title="Alta dermatologica",
                    category="Consulta",
                    veterinarian="Dra. Camila Ferreira (CRMV-RS 14820)",
                    notes=(
                        "Pele totalmente recuperada apos protocolo com banho "
                        "medicamentoso e Simparic 20 a 40kg."
                    ),
                ),
                ClinicalEvent(
                    date="10/06/2026",
                    title="Imunizacao inicial e castracao",
                    category="Procedimento",
                    veterinarian="Dr. Rafael Bastos (CRMV-RS 11904)",
                    notes=(
                        "Orquiectomia realizada com sucesso. Aplicada primeira "
                        "dose de V10."
                    ),
                ),
            ],
            foster_history=[
                "15/06/2026 - Atual: Lar Temporario de Lucia Schmidt (Centro).",
                "05/06/2026 - 15/06/2026: Quarentena na Sede Canil Central.",
            ],
        ),
        Animal(
            id=3,
            name="Mel",
            species="Felina",
            breed="Siames Mestico",
            age_approx="8 meses",
            gender="Femea",
            status="Acolhido",
            intake_date="20/09/2026",
            neutered=False,
            location="Gatil Central - Modulo B",
            rescue_notes="Ninhada resgatada em terreno baldio. Castracao agendada.",
            size="Pequeno (3,1 kg)",
            microchip="90011800294103",
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
            medical_notes=[
                "FIV/FeLV Negativo em teste rapido.",
                "Castracao programada para 10/10.",
            ],
            clinical_events=[
                ClinicalEvent(
                    date="21/09/2026",
                    title="Testagem FIV/FeLV e primeira dose V4",
                    category="Exame",
                    veterinarian="Dra. Camila Ferreira (CRMV-RS 14820)",
                    notes=(
                        "Resultado negativo para retroviroses. Liberada para "
                        "integracao no Modulo B do Gatil."
                    ),
                ),
            ],
            foster_history=[
                "20/09/2026 - Atual: Gatil Central - Modulo B.",
            ],
        ),
        Animal(
            id=4,
            name="Barao",
            species="Canina",
            breed="Pastor Alemao Mestico",
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
            size="Grande (32 kg)",
            microchip="90011800294104",
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
            medical_notes=[
                "Apto para adocao responsavel.",
                "Necessita de espaco amplo.",
            ],
            clinical_events=[
                ClinicalEvent(
                    date="12/05/2026",
                    title="Liberacao clinica para adocao",
                    category="Consulta",
                    veterinarian="Dra. Camila Ferreira (CRMV-RS 14820)",
                    notes=(
                        "Ganho ponderal de 6 kg desde o resgate. Protocolo "
                        "vacinal completo e comportamento estavel."
                    ),
                ),
            ],
            foster_history=[
                "14/03/2026 - Atual: Canil Central - Baia 1.",
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
            size="Pequeno (3,8 kg)",
            microchip="90011800294105",
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
            medical_notes=[
                "Termo de adocao assinado com sucesso.",
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
            foster_history=[
                "15/09/2026 - Atual: Adotada por Ana Paula de Souza.",
                "10/05/2026 - 15/09/2026: Gatil Central - Modulo A.",
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
        StockItem(
            id=6,
            name="Clorexidina Degermante 2% (1L)",
            category="Higiene",
            quantity=6,
            unit="frascos",
            lot_number="CLX-2026-04",
            expiration_date="18/06/2027",
            min_quantity=3,
            status="Normal",
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


def get_priority_alerts(
    animals: list[Animal], stock: list[StockItem]
) -> list[OperationalAlert]:
    """Build prioritized alerts for expiring stock, low stock, and pending vaccines.

    Args:
        animals: Registered animals list.
        stock: Registered stock items list.

    Returns:
        Ordered list of operational alerts requiring volunteer attention.
    """
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
                    use_htmx=False,
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
                    use_htmx=False,
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


def get_recent_activities() -> list[ActivityItem]:
    """Retrieve recent operational movements for the dashboard feed.

    Returns:
        List of ActivityItem instances ordered from newest to oldest.
    """
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
            use_htmx=False,
        ),
        ActivityItem(
            timestamp="10/09 · 09:05",
            category="Estoque",
            title="Alerta de validade no lote NV-2026-09",
            detail="Vacina Nobivac Puppy DP com vencimento em 15/10/2026.",
            action_label="Estoque",
            action_url="/estoque",
            use_htmx=False,
        ),
    ]
