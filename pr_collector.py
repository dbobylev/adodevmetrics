from dataclasses import dataclass, field
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from azure.devops.v7_1.git import GitClient
from azure.devops.v7_1.git.models import GitPullRequestSearchCriteria

from config import Config
from ado_client import with_retry

PAGE_SIZE = 100

# vote: 10=approved, 5=approved with suggestions, 0=no vote, -5=waiting, -10=rejected
APPROVED_VOTES = {10, 5}
COMMENTED_VOTE = -5  # "waiting for author" often means commented


@dataclass
class PRStats:
    created: int = 0
    approved: int = 0
    commented: int = 0


@with_retry()
def _fetch_prs_page(git_client: GitClient, project: str, repo: str,
                    criteria: GitPullRequestSearchCriteria, skip: int) -> list:
    return git_client.get_pull_requests(
        repo, criteria, project=project, top=PAGE_SIZE, skip=skip
    ) or []


@with_retry()
def _fetch_pr_threads(git_client: GitClient, project: str, repo: str, pr_id: int) -> list:
    return git_client.get_threads(repo, pr_id, project=project) or []


def get_pr_stats(git_client: GitClient, config: Config) -> dict[str, PRStats]:
    date_from = datetime.now(timezone.utc) - relativedelta(months=config.months_back)

    criteria = GitPullRequestSearchCriteria(status="all", repository_id=None)

    print(f"Сбор данных по PR за последние {config.months_back} мес...")

    stats: dict[str, PRStats] = {}
    skip = 0
    total = 0

    while True:
        page = _fetch_prs_page(git_client, config.project, config.repository, criteria, skip)
        if not page:
            break

        relevant = []
        stop = False
        for pr in page:
            creation_date = pr.creation_date
            if creation_date and creation_date.replace(tzinfo=timezone.utc) < date_from:
                stop = True
                break
            relevant.append(pr)

        for pr in relevant:
            creator_email = (pr.created_by.unique_name if pr.created_by else "").lower()
            if creator_email:
                stats.setdefault(creator_email, PRStats())
                stats[creator_email].created += 1

            # reviewers из summary
            for reviewer in (pr.reviewers or []):
                email = (reviewer.unique_name or "").lower()
                if not email:
                    continue
                stats.setdefault(email, PRStats())
                vote = reviewer.vote or 0
                if vote in APPROVED_VOTES:
                    stats[email].approved += 1

            # комментарии из threads
            try:
                threads = _fetch_pr_threads(git_client, config.project, config.repository, pr.pull_request_id)
                commenters = set()
                for thread in threads:
                    if thread.is_deleted:
                        continue
                    for comment in (thread.comments or []):
                        if comment.is_deleted or comment.comment_type == "system":
                            continue
                        author = comment.author
                        if not author:
                            continue
                        email = (author.unique_name or "").lower()
                        if email and email != creator_email:
                            commenters.add(email)
                for email in commenters:
                    stats.setdefault(email, PRStats())
                    stats[email].commented += 1
            except Exception:
                pass

        total += len(relevant)
        skip += len(page)

        if total % 50 == 0 or len(page) < PAGE_SIZE or stop:
            print(f"  Обработано PR: {total}")

        if len(page) < PAGE_SIZE or stop:
            break

    print(f"Итого PR: {total}")
    return stats
