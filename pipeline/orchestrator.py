"""
Pipeline orchestrator – 3-stage coordinator.

Stage 1  Apollo   → similar companies
Stage 2  Prospeo  → decision makers + verified emails  (Search + BulkEnrich)
Stage 3  Brevo    → personalised outreach emails sent

EazyReach has been removed. Prospeo now owns the full enrichment
responsibility, producing VerifiedContact objects directly (with emails).
Brevo consumes those contacts unchanged.

Resume logic:
    Stage N is skipped if state.stageN_complete is True AND its result is
    non-None. Crashing mid-Stage-2 will resume from Stage 2 on re-run;
    Stages 1 results are loaded from the cached state file.

Error isolation:
    Per-record errors are absorbed inside each service class.
    Fatal stage errors propagate to cli.py for user-friendly display.
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich import box

from core.logger import get_logger
from core.state import load_state, save_state
from models.schemas import PipelineState
from services.ocean import OceanService
from services.prospeo import ProspeoService
from services.brevo import BrevoService

logger = get_logger(__name__)
console = Console()


# ---------------------------------------------------------------------------
# Checkpoint UI  (shown before Stage 3 / Brevo send)
# ---------------------------------------------------------------------------

def _render_checkpoint(state: PipelineState) -> None:
    """Render the pre-send summary table using rich."""
    n_companies = len(state.ocean_result.companies) if state.ocean_result else 0
    n_contacts  = len(state.prospeo_result.contacts) if state.prospeo_result else 0

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title="[bold yellow]⚡ Pipeline Summary[/bold yellow]",
        title_justify="left",
    )
    table.add_column("Stage", style="dim", width=35)
    table.add_column("Result", justify="right", style="bold green")

    table.add_row("Similar companies found   (Apollo)",    str(n_companies))
    table.add_row("Verified contacts ready   (Prospeo)", str(n_contacts))

    console.print()
    console.print(table)

    if state.prospeo_result and state.prospeo_result.contacts:
        preview = Table(
            box=box.SIMPLE,
            show_header=True,
            header_style="bold magenta",
            title="[bold]Recipients Preview[/bold]",
            title_justify="left",
        )
        preview.add_column("Name",    style="cyan")
        preview.add_column("Title",   style="dim")
        preview.add_column("Company", style="yellow")
        preview.add_column("Email",   style="green")

        for contact in state.prospeo_result.contacts:
            preview.add_row(
                contact.full_name,
                contact.title or "—",
                contact.company_name or "—",
                contact.email,
            )

        console.print(preview)

    console.print()


# ---------------------------------------------------------------------------
# Stage runners
# ---------------------------------------------------------------------------

async def _run_stage1(state: PipelineState, mock: bool) -> PipelineState:
    """Stage 1: Apollo – discover similar companies."""
    if state.stage1_complete and state.ocean_result:
        n = len(state.ocean_result.companies)
        console.print(
            f"  [yellow]↩  Stage 1 cached[/yellow] — {n} companies loaded from state."
        )
        logger.info("Stage 1 skipped (cached). %d companies.", n)
        return state

    console.print("  [cyan]→  Stage 1[/cyan] Discovering similar companies via Apollo…")
    async with OceanService() as svc:
        result = await (
            svc.get_similar_companies_mock(state.seed_domain)
            if mock
            else svc.get_similar_companies(state.seed_domain)
        )

    state.ocean_result = result
    state.stage1_complete = True
    save_state(state)

    n = len(result.companies)
    console.print(f"  [green]✓  Stage 1[/green] Found [bold]{n}[/bold] similar companies.")
    logger.info("Stage 1 complete. %d companies.", n)
    return state


async def _run_stage2(state: PipelineState, mock: bool) -> PipelineState:
    """Stage 2: Prospeo – search for decision makers and enrich their emails."""
    if state.stage2_complete and state.prospeo_result:
        n = len(state.prospeo_result.contacts)
        console.print(
            f"  [yellow]↩  Stage 2 cached[/yellow] — {n} verified contacts loaded from state."
        )
        logger.info("Stage 2 skipped (cached). %d contacts.", n)
        return state

    if not state.ocean_result or not state.ocean_result.companies:
        raise RuntimeError("Stage 2 requires Stage 1 results but none are present.")

    companies = state.ocean_result.companies
    console.print(
        f"  [cyan]→  Stage 2[/cyan] Searching + enriching decision makers across"
        f" [bold]{len(companies)}[/bold] companies via Prospeo…"
    )

    async with ProspeoService() as svc:
        result = await (
            svc.get_contacts_mock(companies)
            if mock
            else svc.get_contacts(companies)
        )

    state.prospeo_result = result
    state.stage2_complete = True
    save_state(state)

    n = len(result.contacts)
    console.print(
        f"  [green]✓  Stage 2[/green] Found [bold]{n}[/bold] verified contacts with emails."
    )
    logger.info("Stage 2 complete. %d verified contacts.", n)
    return state


async def _run_stage3(
    state: PipelineState, mock: bool, auto_confirm: bool
) -> PipelineState:
    """Stage 3: Brevo – send personalised outreach emails."""
    if state.stage3_complete and state.brevo_result:
        n = len(state.brevo_result.emails_sent)
        console.print(
            f"  [yellow]↩  Stage 3 cached[/yellow] — {n} emails already sent."
        )
        logger.info("Stage 3 skipped (cached). %d emails already sent.", n)
        return state

    if not state.prospeo_result or not state.prospeo_result.contacts:
        console.print(
            "  [red]✗  Stage 3 aborted[/red] — no verified contacts to email."
        )
        logger.warning("Stage 3 skipped: no verified contacts.")
        return state

    # ------------------------------------------------------------------
    # Safety checkpoint
    # ------------------------------------------------------------------
    _render_checkpoint(state)

    if not auto_confirm:
        confirmed = Confirm.ask(
            "[bold yellow]Proceed with sending emails?[/bold yellow]",
            default=False,
        )
        if not confirmed:
            console.print(
                "\n[bold red]Aborted by user.[/bold red] "
                "No emails were sent. State is preserved — re-run to retry Stage 3."
            )
            logger.info("Stage 3 aborted by user at confirmation checkpoint.")
            sys.exit(0)

    contacts = state.prospeo_result.contacts
    console.print(
        f"  [cyan]→  Stage 3[/cyan] Sending [bold]{len(contacts)}[/bold]"
        " personalised emails via Brevo…"
    )

    async with BrevoService() as svc:
        result = await (
            svc.send_emails_mock(contacts)
            if mock
            else svc.send_emails(contacts)
        )

    state.brevo_result = result
    state.stage3_complete = True
    save_state(state)

    n_sent = len(result.emails_sent)
    n_fail = len(result.emails_failed)
    console.print(
        f"  [green]✓  Stage 3[/green] "
        f"[bold]{n_sent}[/bold] sent, [bold red]{n_fail}[/bold red] failed."
    )
    if result.emails_failed:
        for f in result.emails_failed:
            console.print(f"    [red]✗[/red] {f.get('email')} — {f.get('error')}")
    logger.info("Stage 3 complete. Sent=%d, Failed=%d.", n_sent, n_fail)
    return state


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_pipeline(
    domain: str,
    mock: bool = False,
    reset: bool = False,
    auto_confirm: bool = False,
) -> PipelineState:
    """
    Execute the 3-stage cold outreach pipeline.

    Args:
        domain:       Seed company domain (e.g. 'stripe.com').
        mock:         If True, use local fixtures (no API credits consumed).
        reset:        If True, delete cached state and start from scratch.
        auto_confirm: If True, skip the Stage 3 send confirmation prompt.

    Returns:
        Final PipelineState.
    """
    from core.state import reset_state

    domain = domain.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")

    console.print(
        Panel(
            f"[bold cyan]Cold Outreach Pipeline[/bold cyan]\n"
            f"Seed domain : [bold]{domain}[/bold]\n"
            f"Mode        : [bold]{'[yellow]MOCK[/yellow]' if mock else '[green]LIVE[/green]'}[/bold]",
            expand=False,
            border_style="bright_blue",
        )
    )
    console.print()

    if reset:
        state = reset_state(domain)
        console.print("[dim]State reset. Starting from scratch.[/dim]\n")
    else:
        state = load_state(domain)
        if any([state.stage1_complete, state.stage2_complete]):
            console.print(
                "[dim]Resuming from cached state "
                f"(last updated: {state.last_updated.strftime('%Y-%m-%d %H:%M:%S')} UTC)[/dim]\n"
            )

    state = await _run_stage1(state, mock)
    state = await _run_stage2(state, mock)
    state = await _run_stage3(state, mock, auto_confirm)

    return state
