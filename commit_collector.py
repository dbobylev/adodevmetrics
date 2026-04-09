import difflib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from azure.devops.v7_1.git import GitClient
from azure.devops.v7_1.git.models import GitQueryCommitsCriteria, GitVersionDescriptor

from config import Config
from ado_client import with_retry

PAGE_SIZE = 100

# Binary file extensions — skipped when counting line diffs.
# Oracle PL/SQL extensions (.bdy, .spc, .trg, .prc, .fun, .typ, .tps, .tpb,
# .vw, .seq, .syn, .idx, .sql, .pls, .plb) are text and NOT listed here.
BINARY_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg', '.webp',
    '.pdf', '.zip', '.tar', '.gz', '.7z', '.rar',
    '.exe', '.dll', '.so', '.dylib', '.obj', '.class',
    '.pyc', '.pdb', '.bin', '.dat',
    '.ttf', '.otf', '.woff', '.woff2',
    '.mp3', '.mp4', '.avi', '.mov',
    '.xlsx', '.docx', '.pptx',
}


@dataclass
class CommitInfo:
    commit_id: str
    author_name: str
    author_email: str
    date: datetime
    message: str
    lines_added: int = 0
    lines_deleted: int = 0


def _is_text_file(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext not in BINARY_EXTENSIONS


def _get_field(obj, *names):
    if obj is None:
        return None

    if isinstance(obj, dict):
        for name in names:
            if name in obj and obj[name] is not None:
                return obj[name]
        return None

    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


def _normalize_change(change) -> dict | None:
    # Azure DevOps Python SDK declares GitCommitChanges.changes as [object],
    # so depending on deserialization we may get either SDK models or raw dicts.
    item = _get_field(change, 'item')
    path = (
        _get_field(item, 'path')
        or _get_field(change, 'source_server_item', 'sourceServerItem')
        or _get_field(change, 'original_path', 'originalPath')
    )
    if not path:
        return None

    is_folder = _get_field(item, 'is_folder', 'isFolder')
    if is_folder is None:
        git_object_type = _get_field(
            item, 'git_object_type', 'gitObjectType', 'object_type', 'objectType'
        )
        is_folder = str(git_object_type or '').lower() == 'tree'
    if is_folder or not _is_text_file(path):
        return None

    return {
        'path': path,
        'change_type': str(_get_field(change, 'change_type', 'changeType') or '').lower(),
        'original_path': _get_field(change, 'original_path', 'originalPath') or path,
    }


@with_retry()
def _fetch_commits_page(git_client: GitClient, project: str, repo: str,
                        criteria: GitQueryCommitsCriteria, skip: int) -> list:
    criteria.skip = skip
    criteria.top = PAGE_SIZE
    return git_client.get_commits(repo, criteria, project=project) or []


@with_retry()
def _fetch_commit_changes(git_client: GitClient, project: str, repo: str, commit_id: str):
    return git_client.get_changes(commit_id, repo, project=project)


@with_retry()
def _fetch_single_commit(git_client: GitClient, project: str, repo: str, commit_id: str):
    return git_client.get_commit(commit_id, repo, project=project)


@with_retry()
def _fetch_item_content(git_client: GitClient, project: str, repo: str,
                        path: str, commit_id: str) -> str | None:
    vd = GitVersionDescriptor(version=commit_id, version_type="commit")
    item = git_client.get_item(repo, path, project=project,
                               include_content=True, version_descriptor=vd)
    return item.content if item else None


def _diff_lines(old: str | None, new: str | None) -> tuple[int, int]:
    old_lines = old.splitlines() if old else []
    new_lines = new.splitlines() if new else []
    added = deleted = 0
    for line in difflib.unified_diff(old_lines, new_lines, n=0, lineterm=''):
        if line.startswith('+') and not line.startswith('+++'):
            added += 1
        elif line.startswith('-') and not line.startswith('---'):
            deleted += 1
    return added, deleted


def _count_lines_from_changes(git_client: GitClient, project: str, repo: str,
                               commit_id: str, changes) -> tuple[int, int]:
    if not changes or not changes.changes:
        return 0, 0

    file_changes = []
    for change in changes.changes:
        normalized = _normalize_change(change)
        if normalized:
            file_changes.append(normalized)

    if not file_changes:
        return 0, 0

    needs_parent = any(
        c['change_type'] not in ('add',) for c in file_changes
    )
    parent_id = None
    if needs_parent:
        try:
            single = _fetch_single_commit(git_client, project, repo, commit_id)
            if single.parents:
                parent_id = single.parents[0]
        except Exception:
            pass

    total_added = total_deleted = 0
    for change in file_changes:
        path = change['path']
        old_path = change['original_path']
        ct = change['change_type']
        try:
            if 'add' in ct and 'delete' not in ct:
                new_content = _fetch_item_content(git_client, project, repo, path, commit_id)
                a, d = _diff_lines(None, new_content)
            elif 'delete' in ct and parent_id:
                old_content = _fetch_item_content(git_client, project, repo, old_path, parent_id)
                a, d = _diff_lines(old_content, None)
            elif parent_id:  # edit / rename
                old_content = _fetch_item_content(git_client, project, repo, old_path, parent_id)
                new_content = _fetch_item_content(git_client, project, repo, path, commit_id)
                a, d = _diff_lines(old_content, new_content)
            else:
                continue
            total_added += a
            total_deleted += d
        except Exception:
            pass  # best-effort: skip individual file on error

    return total_added, total_deleted


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
                info.lines_added, info.lines_deleted = _count_lines_from_changes(
                    git_client, config.project, config.repository, raw.commit_id, changes
                )
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
