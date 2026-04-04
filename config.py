import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    organization_url: str
    project: str
    repository: str
    branch: str
    pat: str
    months_back: int


def load_config() -> Config:
    required = [
        "ADO_ORGANIZATION_URL",
        "ADO_PROJECT",
        "ADO_REPOSITORY",
        "ADO_BRANCH",
        "ADO_PAT",
        "MONTHS_BACK",
    ]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise ValueError(f"Отсутствуют обязательные переменные окружения: {', '.join(missing)}")

    return Config(
        organization_url=os.environ["ADO_ORGANIZATION_URL"].rstrip("/"),
        project=os.environ["ADO_PROJECT"],
        repository=os.environ["ADO_REPOSITORY"],
        branch=os.environ["ADO_BRANCH"],
        pat=os.environ["ADO_PAT"],
        months_back=int(os.environ["MONTHS_BACK"]),
    )
