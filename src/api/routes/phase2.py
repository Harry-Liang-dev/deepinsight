"""Reserved Phase Two routes that are intentionally unavailable in the MVP."""

from typing import Never

from fastapi import APIRouter

from src.api.errors import phase_two_not_implemented

router = APIRouter(prefix="/v1", tags=["phase-two"])


def _unavailable() -> Never:
    raise phase_two_not_implemented()


@router.post("/phase2/factors/mine", response_model=None)
async def mine_factors() -> None:
    """Reject factor-mining operations during Phase One."""
    _unavailable()


@router.post("/phase2/router/select", response_model=None)
async def select_router() -> None:
    """Reject Agent-router operations during Phase One."""
    _unavailable()


@router.post("/phase2/training/run", response_model=None)
async def run_training() -> None:
    """Reject model-training operations during Phase One."""
    _unavailable()


@router.post("/phase2/backtest/run", response_model=None)
async def run_backtest() -> None:
    """Reject backtesting operations during Phase One."""
    _unavailable()


@router.post("/phase2/execution/paper", response_model=None)
async def execute_paper_order() -> None:
    """Reject paper-execution operations during Phase One."""
    _unavailable()


@router.post("/phase2/execution/live", response_model=None)
async def execute_live_order() -> None:
    """Reject live-execution operations during Phase One."""
    _unavailable()
