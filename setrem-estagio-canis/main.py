"""Start Canis."""

import logging

VERMELHO = "\033[31m"
VERDE = "\033[32m"
AZUL = "\033[34m"
RESET = "\033[0m"


logging.basicConfig(
    level=logging.INFO,
    format=f"{VERDE}%(asctime)s{RESET} | {VERMELHO}%(levelname)s{RESET} | {AZUL}%(filename)s:%(lineno)d{RESET} | %(message)s",  # noqa: E501
)
_LOGGER = logging.getLogger(__name__)


if __name__ == "__main__":
    _LOGGER.info("Iniciando o Canis")
