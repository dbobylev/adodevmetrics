import sys
from config import load_config
from ado_client import create_git_client
from commit_collector import get_commits
from pr_collector import get_pr_stats
from excel_exporter import export


def main():
    try:
        config = load_config()
    except ValueError as e:
        print(f"Ошибка конфигурации: {e}")
        print("Скопируйте .env.example в .env и заполните значения.")
        sys.exit(1)

    print(f"Организация : {config.organization_url}")
    print(f"Проект      : {config.project}")
    print(f"Репозиторий : {config.repository}")
    print(f"Ветка       : {config.branch}")
    print(f"Период      : {config.months_back} мес.")
    print()

    git_client = create_git_client(config)

    commits = get_commits(git_client, config)
    print()
    pr_stats, pr_list = get_pr_stats(git_client, config)
    print()

    filename = export(commits, pr_list, config.repository)
    print(f"Отчёт сохранён: {filename}")


if __name__ == "__main__":
    main()
