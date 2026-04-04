import time
import functools
from azure.devops.connection import Connection
from azure.devops.v7_1.git import GitClient
from msrest.authentication import BasicAuthentication
from msrest.exceptions import HttpOperationError

from config import Config


def create_git_client(config: Config) -> GitClient:
    credentials = BasicAuthentication("", config.pat)
    connection = Connection(base_url=config.organization_url, creds=credentials)
    return connection.clients.get_git_client()


def with_retry(max_attempts: int = 5, base_delay: float = 1.0):
    """Декоратор с экспоненциальным backoff для повторных попыток при ошибках API."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = base_delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except HttpOperationError as e:
                    status = getattr(e.response, "status_code", None)
                    if status == 429 or (status and status >= 500):
                        if attempt == max_attempts:
                            raise
                        print(f"  [retry {attempt}/{max_attempts}] HTTP {status}, ожидание {delay:.1f}с...")
                        time.sleep(delay)
                        delay *= 2
                    else:
                        raise
        return wrapper
    return decorator
