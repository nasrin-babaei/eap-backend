# app/schemas/report.py
# US-010 (IT35-63) — Report schemas matching OpenAPI spec exactly

from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


class ReportFilters(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    request_type: Optional[str] = None
    status: Optional[str] = None


class ReportTotals(BaseModel):
    total_requests: int
    pending: int
    approved: int
    rejected: int
    completed: int
    cancelled: int


class RequestReportResponse(BaseModel):
    filters: ReportFilters
    totals: ReportTotals
    approval_rate: float
    rejection_rate: float
    generated_at: datetime