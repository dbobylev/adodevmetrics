from dataclasses import dataclass, field
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from azure.devops.v7_1.git import GitClient
from azure.devops.v7_1.git.models import GitQueryCommitsCriteria, GitVersionDescriptor

from config import Config
from ado_client import with_retry

PAGE_SIZE = 100


@dataclass
class CommitInfo:
    commit_id: str
    author_name: str
    author_email: str
    date: datetime
    message: str
    lines_added: int = 0
    lines_deleted: int = 0


@with_retry()
def _fetch_commits_page(git_client: GitClient, project: str, repo: str,
                        criteria: GitQueryCommitsCriteria, skip: int) -> list:
    criteria.skip = skip
    criteria.top = PAGE_SIZE
    return git_client.get_commits(repo, criteria, project=project) or []


@with_retry()
def _fetch_commit_changes(git_client: GitClient, project: str, repo: str, commit_id: str):
    return git_client.get_changes(commit_id, repo, project=project)


def _count_lines(changes) -> tuple[int, int]:
    added = 0
    deleted = 0
    if not changes or not changes.changes:
        return added, deleted
    for change in changes.changes:
        if change.change_counts:
            added += change.change_counts.get("Add", 0) + change.change_counts.get("Edit", 0)
            deleted += change.change_counts.get("Delete", 0) + change.change_counts.get("Edit", 0)
    return added, deleted


def get_commits(git_client: GitClient, config: Config) -> list[CommitInfo]:
    date_from = datetime.now(timezone.utc) - relativedelta(months=config.months_back)

    version = GitVersionDescriptor(version=config.branch, version_type="branch")
    criteria = GitQueryCommitsCriteria(
        from_date=date_from.strftime("%Y-%m-%dT%H:%M:%SZ"),
        item_version=version,
    )

    print(f"Сбор коммитов из ветки '{config.branch}' за последние {config.months_back} мес...")

    all_commits: list[CommitInfo] = []
    skip = 0

    while True:
        page = _fetch_commits_page(git_client, config.project, config.repository, criteria, skip)
        if not page:
            break

        for raw in page:
            # parents не возвращается list-эндпоинтом ADO, поэтому определяем
            # merge-коммит по стандартному префиксу сообщения Azure DevOps
            comment = raw.comment or ""
            if comment.startswith("Merged PR") or comment.startswith("Merge branch") or comment.startswith("Merge pull request"):
                continue

            author = raw.author
            info = CommitInfo(
                commit_id=raw.commit_id,
                author_name=author.name if author else "",
                author_email=(author.email if author else "").lower(),
                date=author.date if author else datetime.now(timezone.utc),
                message=(raw.comment or "").splitlines()[0],
            )

            try:
                changes = _fetch_commit_changes(git_client, config.project, config.repository, raw.commit_id)
                info.lines_added, info.lines_deleted = _count_lines(changes)
            except Exception:
                pass

            all_commits.append(info)

        skip += len(page)
        if len(all_commits) % 100 == 0 or len(page) < PAGE_SIZE:
            print(f"  Обработано коммитов: {len(all_commits)}")

        if len(page) < PAGE_SIZE:
            break

    print(f"Итого коммитов: {len(all_commits)}")
    return all_commits
