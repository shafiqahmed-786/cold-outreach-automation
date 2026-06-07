"""
CLI layer – argument parsing and rich terminal output.

Keeps main.py as a clean one-liner by handling all argument parsing,
validation, and final result rendering here.

Usage:
    python main.py --domain stripe.com
    python main.py --domain stripe.com --mock
    python main.py --domain stripe.com --reset
    python main.py --domain stripe.com --mock --yes   # skip confirmation
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import traceback
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="outreach-pipeline",
        description=(
            "Automated cold outreach pipeline: domain → similar companies "
            "→ decision makers → verified emails → personalised sends."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run against live APIs
  python main.py --domain stripe.com

  # Safe test with local mock data (no API credits used)
  python main.py --domain stripe.com --mock

  # Reset cached state and start over
  python main.py --domain stripe.com --reset

  # Skip confirmation prompt (CI/automation)
  python main.py --domain stripe.com --mock --yes
        """,
    )
    parser.add_argument(
        "--domain",
        required=True,
        metavar="DOMAIN",
        help="Seed company domain, e.g. stripe.com",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        default=False,
        help="Use local mock data instead of real API calls (no credits consumed).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        default=False,
        help="Delete any cached pipeline state and start from scratch.",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        default=False,
        dest="auto_confirm",
        help="Skip the Stage 4 send confirmation prompt (for automation).",
    )
    return parser


def _render_final_summary(state) -> None:  # type: ignore[override]
    """Print the post-run summary panel."""
    n_companies = len(state.ocean_result.companies) if state.ocean_result else 0
    n_contacts  = len(state.prospeo_result.contacts) if state.prospeo_result else 0
    n_sent      = len(state.brevo_result.emails_sent) if state.brevo_result else 0
    n_failed    = len(state.brevo_result.emails_failed) if state.brevo_result else 0

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold green",
        title="[bold green]Pipeline Complete[/bold green]",
        title_justify="left",
    )
    table.add_column("Metric", style="dim", width=40)
    table.add_column("Count", justify="right", style="bold")

    table.add_row("Similar companies discovered   (Apollo)",   str(n_companies))
    table.add_row("Verified contacts with emails  (Prospeo)", str(n_contacts))
    table.add_row("[green]Emails sent[/green]              (Brevo)",   f"[green]{n_sent}[/green]")
    if n_failed:
        table.add_row("[red]Emails failed[/red]", f"[red]{n_failed}[/red]")

    console.print()
    console.print(table)
    console.print(
        f"\n[dim]State saved → pipeline_state.json "
        f"| Log → logs/pipeline.log[/dim]"
    )


def run() -> None:
    """
    Entry point called by main.py.
    Parses args, runs the async pipeline, renders the final summary.
    """
    parser = _build_parser()
    args = parser.parse_args()

    # Late import so the logger initialises after arg parsing
    from pipeline.orchestrator import run_pipeline

    console.print()
    try:
        state = asyncio.run(
            run_pipeline(
                domain=args.domain,
                mock=args.mock,
                reset=args.reset,
                auto_confirm=args.auto_confirm,
            )
        )
        _render_final_summary(state)

    except KeyboardInterrupt:
        console.print(
            "\n[bold red]Interrupted.[/bold red] "
            "Pipeline state has been saved — re-run to resume."
        )
        sys.exit(130)

    except Exception as exc:
        console.print(
            Panel(
                f"[bold red]Pipeline error:[/bold red] {exc}\n\n"
                "[dim]Check logs/pipeline.log for full traceback.[/dim]",
                border_style="red",
                title="Error",
            )
        )
        # Full traceback goes to the log file, not the terminal
        from core.logger import get_logger
        logger = get_logger("cli")
        logger.error("Unhandled pipeline error:\n%s", traceback.format_exc())
        sys.exit(1)