from collections import defaultdict
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from commit_collector import CommitInfo
from pr_collector import PRStats

HEADER_FILL = PatternFill("solid", fgColor="4472C4")
HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _apply_header(ws, headers: list[str]):
    ws.append(headers)
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGN
    ws.freeze_panes = "A2"


def _autofit(ws):
    for col_idx, col_cells in enumerate(ws.columns, start=1):
        max_len = max(
            (len(str(cell.value)) if cell.value is not None else 0 for cell in col_cells),
            default=10,
        )
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 2, 60)


def export(commits: list[CommitInfo], pr_stats: dict[str, PRStats], repo_name: str) -> str:
    wb = Workbook()

    # --- Лист 1: Commits ---
    ws_commits = wb.active
    ws_commits.title = "Commits"
    _apply_header(ws_commits, [
        "Author", "Email", "Date", "Commit Hash", "Message", "Lines Added", "Lines Deleted"
    ])

    for c in commits:
        ws_commits.append([
            c.author_name,
            c.author_email,
            c.date.strftime("%Y-%m-%d %H:%M") if c.date else "",
            c.commit_id[:8],
            c.message,
            c.lines_added,
            c.lines_deleted,
        ])

    _autofit(ws_commits)

    # --- Лист 2: Summary ---
    ws_summary = wb.create_sheet("Summary")
    _apply_header(ws_summary, [
        "Author", "Email", "Commits",
        "Lines Added", "Lines Deleted",
        "PRs Created", "PRs Approved", "PRs Commented",
    ])

    # Агрегация по email
    author_names: dict[str, str] = {}
    commits_count: dict[str, int] = defaultdict(int)
    lines_added: dict[str, int] = defaultdict(int)
    lines_deleted: dict[str, int] = defaultdict(int)

    for c in commits:
        email = c.author_email
        author_names[email] = c.author_name
        commits_count[email] += 1
        lines_added[email] += c.lines_added
        lines_deleted[email] += c.lines_deleted

    all_emails = sorted(
        set(list(commits_count.keys()) + list(pr_stats.keys())),
        key=lambda e: commits_count.get(e, 0),
        reverse=True,
    )

    for email in all_emails:
        pr = pr_stats.get(email, PRStats())
        ws_summary.append([
            author_names.get(email, ""),
            email,
            commits_count.get(email, 0),
            lines_added.get(email, 0),
            lines_deleted.get(email, 0),
            pr.created,
            pr.approved,
            pr.commented,
        ])

    _autofit(ws_summary)

    filename = f"{repo_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    wb.save(filename)
    return filename
