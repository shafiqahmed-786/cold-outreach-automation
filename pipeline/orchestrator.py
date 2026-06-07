"""
Pipeline orchestrator – the single async coordinator for all four stages.

Responsibilities:
1. Load (or resume) PipelineState from disk.
2. Execute each stage in sequence, skipping completed ones.
3. Persist state atomically after every stage completes.
4. Display a rich terminal confirmation checkpoint before Stage 4 (Brevo).
5. Return the final PipelineState for CLI reporting.

Resume logic:
    Stage N is skipped if state.stageN_complete is True AND its result is
    non-None. This means a partial run (e.g., crashed at Stage 3) will
    resume from exactly the last incomplete stage on re-invocation.

Error isolation:
    A fatal error within any stage propagates up and is caught by cli.py,
    which displays a user-friendly message. Per-record errors are absorbed
    inside each service class and do not reach the orchestrator.
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
from services.eazyreach import EazyreachService
from services.brevo import BrevoService

logger = get_logger(__name__)
console = Console()


# ---------------------------------------------------------------------------
# Checkpoint UI
# ---------------------------------------------------------------------------

def _render_checkpoint(state: PipelineState) -> None:
    """Render the pre-send summary table using rich."""
    n_companies = len(state.ocean_result.companies) if state.ocean_result else 0
    n_dms = len(state.prospeo_result.decision_makers) if state.prospeo_result else 0
    n_emails = len(state.eazyreach_result.contacts) if state.eazyreach_result else 0

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title="[bold yellow]⚡ Pipeline Summary[/bold yellow]",
        title_justify="left",
    )
    table.add_column("Stage", style="dim", width=30)
    table.add_column("Result", justify="right", style="bold green")

    table.add_row("Similar companies found", str(n_companies))
    table.add_row("Decision makers identified", str(n_dms))
    table.add_row("Verified emails ready to send", str(n_emails))

    console.print()
    console.print(table)

    if state.eazyreach_result and state.eazyreach_result.contacts:
        preview = Table(
            box=box.SIMPLE,
            show_header=True,
            header_style="bold magenta",
            title="[bold]Recipients Preview[/bold]",
            title_justify="left",
        )
        preview.add_column("Name", style="cyan")
        preview.add_column("Title", style="dim")
        preview.add_column("Company", style="yellow")
        preview.add_column("Email", style="green")

        for contact in state.eazyreach_result.contacts:
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
    """Stage 1: Ocean.io – discover similar companies."""
    if state.stage1_complete and state.ocean_result:
        n = len(state.ocean_result.companies)
        console.print(
            f"  [yellow]↩  Stage 1 cached[/yellow] — {n} companies loaded from state."
        )
        logger.info("Stage 1 skipped (cached). %d companies.", n)
        return state

    console.print("  [cyan]→  Stage 1[/cyan] Discovering similar companies via Ocean.io…")
    async with OceanService() as svc:
        if mock:
            result = await svc.get_similar_companies_mock(state.seed_domain)
        else:
            result = await svc.get_similar_companies(state.seed_domain)

    state.ocean_result = result
    state.stage1_complete = True
    save_state(state)

    n = len(result.companies)
    console.print(f"  [green]✓  Stage 1[/green] Found [bold]{n}[/bold] similar companies.")
    logger.info("Stage 1 complete. %d companies.", n)
    return state


async def _run_stage2(state: PipelineState, mock: bool) -> PipelineState:
    """Stage 2: Prospeo – find decision makers for each company."""
    if state.stage2_complete and state.prospeo_result:
        n = len(state.prospeo_result.decision_makers)
        console.print(
            f"  [yellow]↩  Stage 2 cached[/yellow] — {n} decision makers loaded from state."
        )
        logger.info("Stage 2 skipped (cached). %d decision makers.", n)
        return state

    if not state.ocean_result or not state.ocean_result.companies:
        raise RuntimeError("Stage 2 requires Stage 1 results but none are present.")

    companies = state.ocean_result.companies
    console.print(
        f"  [cyan]→  Stage 2[/cyan] Finding decision makers across"
        f" [bold]{len(companies)}[/bold] companies via Prospeo…"
    )

    async with ProspeoService() as svc:
        if mock:
            result = await svc.get_decision_makers_mock(companies)
        else:
            result = await svc.get_decision_makers(companies)

    state.prospeo_result = result
    state.stage2_complete = True
    save_state(state)

    n = len(result.decision_makers)
    console.print(f"  [green]✓  Stage 2[/green] Found [bold]{n}[/bold] decision makers.")
    logger.info("Stage 2 complete. %d decision makers.", n)
    return state


async def _run_stage3(state: PipelineState, mock: bool) -> PipelineState:
    """Stage 3: Eazyreach – verify work emails from LinkedIn profiles."""
    if state.stage3_complete and state.eazyreach_result:
        n = len(state.eazyreach_result.contacts)
        console.print(
            f"  [yellow]↩  Stage 3 cached[/yellow] — {n} verified emails loaded from state."
        )
        logger.info("Stage 3 skipped (cached). %d verified contacts.", n)
        return state

    if not state.prospeo_result or not state.prospeo_result.decision_makers:
        raise RuntimeError("Stage 3 requires Stage 2 results but none are present.")

    dms = state.prospeo_result.decision_makers
    console.print(
        f"  [cyan]→  Stage 3[/cyan] Enriching emails for"
        f" [bold]{len(dms)}[/bold] decision makers via Eazyreach…"
    )

    async with EazyreachService() as svc:
        if mock:
            result = await svc.get_verified_emails_mock(dms)
        else:
            result = await svc.get_verified_emails(dms)

    state.eazyreach_result = result
    state.stage3_complete = True
    save_state(state)

    n = len(result.contacts)
    console.print(f"  [green]✓  Stage 3[/green] Verified [bold]{n}[/bold] work emails.")
    logger.info("Stage 3 complete. %d verified contacts.", n)
    return state


async def _run_stage4(
    state: PipelineState, mock: bool, auto_confirm: bool
) -> PipelineState:
    """Stage 4: Brevo – send personalised outreach emails."""
    if state.stage4_complete and state.brevo_result:
        n = len(state.brevo_result.emails_sent)
        console.print(
            f"  [yellow]↩  Stage 4 cached[/yellow] — {n} emails already sent."
        )
        logger.info("Stage 4 skipped (cached). %d emails already sent.", n)
        return state

    if not state.eazyreach_result or not state.eazyreach_result.contacts:
        console.print(
            "  [red]✗  Stage 4 aborted[/red] — no verified contacts to email."
        )
        logger.warning("Stage 4 skipped: no verified contacts.")
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
                "No emails were sent. State is preserved — re-run to retry Stage 4."
            )
            logger.info("Stage 4 aborted by user at confirmation checkpoint.")
            sys.exit(0)

    contacts = state.eazyreach_result.contacts
    console.print(
        f"  [cyan]→  Stage 4[/cyan] Sending [bold]{len(contacts)}[/bold]"
        " personalised emails via Brevo…"
    )

    async with BrevoService() as svc:
        if mock:
            result = await svc.send_emails_mock(contacts)
        else:
            result = await svc.send_emails(contacts)

    state.brevo_result = result
    state.stage4_complete = True
    save_state(state)

    n_sent = len(result.emails_sent)
    n_fail = len(result.emails_failed)
    console.print(
        f"  [green]✓  Stage 4[/green] "
        f"[bold]{n_sent}[/bold] sent, [bold red]{n_fail}[/bold red] failed."
    )
    if result.emails_failed:
        for f in result.emails_failed:
            console.print(
                f"    [red]✗[/red] {f.get('email')} — {f.get('error')}"
            )
    logger.info("Stage 4 complete. Sent=%d, Failed=%d.", n_sent, n_fail)
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
    Execute the full 4-stage cold outreach pipeline.

    Args:
        domain:       Seed company domain (e.g. 'stripe.com').
        mock:         If True, use local fixtures instead of real API calls.
        reset:        If True, delete any cached state and start fresh.
        auto_confirm: If True, skip the Stage 4 confirmation prompt (useful
                      for CI/non-interactive environments).

    Returns:
        Final PipelineState after all stages complete (or abort).
    """
    from core.state import reset_state  # local import avoids circular at module level

    # Normalise domain
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

    # ------------------------------------------------------------------
    # State initialisation
    # ------------------------------------------------------------------
    if reset:
        state = reset_state(domain)
        console.print("[dim]State reset. Starting from scratch.[/dim]\n")
    else:
        state = load_state(domain)
        if any([state.stage1_complete, state.stage2_complete, state.stage3_complete]):
            console.print(
                "[dim]Resuming from cached state "
                f"(last updated: {state.last_updated.strftime('%Y-%m-%d %H:%M:%S')} UTC)[/dim]\n"
            )

    # ------------------------------------------------------------------
    # Stage execution (sequential; each saves state on completion)
    # ------------------------------------------------------------------
    state = await _run_stage1(state, mock)
    state = await _run_stage2(state, mock)
    state = await _run_stage3(state, mock)
    state = await _run_stage4(state, mock, auto_confirm)

    return state