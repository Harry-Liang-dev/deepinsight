"""Verify that Phase Two reservations contain no executable implementations."""

from __future__ import annotations

import inspect

import pytest

from src.phase2_reserved import (
    BaseBacktestEngine,
    BaseExecutionEngine,
    BaseFactorMiner,
    BaseMarketRouter,
    BaseStrategyPool,
    BaseTrainingPipeline,
)


@pytest.mark.parametrize(
    "contract",
    [
        BaseMarketRouter,
        BaseFactorMiner,
        BaseTrainingPipeline,
        BaseBacktestEngine,
        BaseExecutionEngine,
        BaseStrategyPool,
    ],
)
def test_phase_two_contracts_are_abstract_and_non_instantiable(
    contract: type[object],
) -> None:
    """Phase One must reserve boundaries without shipping future behavior."""

    assert inspect.isabstract(contract)
    with pytest.raises(TypeError):
        contract()
