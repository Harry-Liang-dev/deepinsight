"""Research report task and retrieval routes."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, status

from src.api.dependencies import (
    get_report_query_service,
    get_report_task_service,
)
from src.api.errors import not_found
from src.api.services import ReportQueryService, ReportTaskService
from src.schemas import GenerateReportRequest, ResearchReport, TaskStatusResponse

router = APIRouter(prefix="/v1/reports", tags=["reports"])


@router.post(
    "/generate",
    response_model=TaskStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_research_task(
    request: GenerateReportRequest,
    background_tasks: BackgroundTasks,
    task_service: Annotated[ReportTaskService, Depends(get_report_task_service)],
) -> TaskStatusResponse:
    """Create a research task and schedule its local execution."""
    task = task_service.submit(request)
    background_tasks.add_task(
        _run_report_task,
        task_service,
        task.job_id,
        request,
    )
    return task


@router.get("/jobs/{job_id}", response_model=TaskStatusResponse)
async def get_research_task(
    job_id: str,
    task_service: Annotated[ReportTaskService, Depends(get_report_task_service)],
) -> TaskStatusResponse:
    """Return the current status of a research task."""
    task = task_service.get_status(job_id)
    if task is None:
        raise not_found(
            code="job_not_found",
            message=f"Research job '{job_id}' was not found.",
        )
    return task


@router.get("/{report_id}", response_model=ResearchReport)
async def get_research_report(
    report_id: str,
    report_service: Annotated[ReportQueryService, Depends(get_report_query_service)],
) -> ResearchReport:
    """Return a previously generated research report."""
    report = report_service.get(report_id)
    if report is None:
        raise not_found(
            code="report_not_found",
            message=f"Research report '{report_id}' was not found.",
        )
    return report


async def _run_report_task(
    task_service: ReportTaskService,
    job_id: str,
    request: GenerateReportRequest,
) -> None:
    """Run one local task after the response is prepared."""

    task_service.run(job_id, request)
