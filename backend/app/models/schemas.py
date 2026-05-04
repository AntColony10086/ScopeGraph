"""Pydantic request/response schemas for the API layer."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------- Auth ----------

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    member_level: str
    role: str = "user"
    accessible_enterprises: list[str] = Field(default_factory=list)


class TokenPayload(BaseModel):
    user_id: str
    username: str
    role: str = "user"
    accessible_enterprises: list[str] = Field(default_factory=list)
    exp: datetime


# ---------- Chat ----------

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    image_path: Optional[str] = None
    file_path: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    intent: Optional[str] = None
    need_confirmation: bool = False
    confirmation_summary: Optional[str] = None
    escalation: bool = False


class ConfirmActionRequest(BaseModel):
    session_id: str
    operation_id: Optional[str] = None
    action: Optional[Literal["confirm", "cancel"]] = None
    confirmed: Optional[bool] = None


# ---------- SSE Event Types ----------

class SSEEvent(BaseModel):
    event: Literal["message", "thinking", "confirmation", "escalation", "error", "done"]
    data: str


# ---------- User Profile ----------

class UserProfileResponse(BaseModel):
    user_id: str
    username: str
    nickname: Optional[str] = None
    member_level: str = "normal"
    total_orders: int = 0
    total_spend: float = 0.0
    favorite_categories: list[str] = Field(default_factory=list)
    role: str = "user"
    accessible_enterprises: list[str] = Field(default_factory=list)
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    phone: Optional[str] = None


class UserProfileUpdateRequest(BaseModel):
    nickname: Optional[str] = None
    bio: Optional[str] = None
    phone: Optional[str] = None


# ---------- Data CRUD ----------

class ObservationRow(BaseModel):
    """One enterprise×year×indicator data point (a flat row of the graph)."""
    order_id: int
    customer_id: str
    enterprise: str
    indicator: str
    indicator_id: int
    category: Optional[str] = None
    year: int
    value: float
    unit: Optional[str] = None
    source: Optional[str] = None


class ObservationCreateRequest(BaseModel):
    customer_id: str
    indicator_id: int
    year: int
    value: float


class ObservationUpdateRequest(BaseModel):
    order_id: int
    indicator_id: int
    value: float


class ObservationDeleteRequest(BaseModel):
    order_id: int
    indicator_id: int


class EnterpriseRow(BaseModel):
    customer_id: str
    name: str
    city: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None


class IndicatorRow(BaseModel):
    indicator_id: int
    name: str
    category: Optional[str] = None
    unit: Optional[str] = None


# ---------- Dashboard ----------

class DashboardMeta(BaseModel):
    visibleScope: Literal["all", "bound_enterprises"]
    latestYear: int
    currentYear: int
    lastUpdatedAt: Optional[str] = None
    pollingSeconds: int = 15


class DashboardKpis(BaseModel):
    cumulativeEmissionTons: float
    latestYearEmissionTons: float
    latestYearEmissionYoyRate: Optional[float] = None
    fiveYearEmissionChangeRate: Optional[float] = None
    totalElectricityKwh: Optional[float] = None
    dominantIndustryName: Optional[str] = None
    dominantIndustryPercent: Optional[float] = None


class DashboardYearly(BaseModel):
    year: int
    scope1EmissionTons: float
    scope2EmissionTons: float
    totalEmissionTons: float


class DashboardEnterpriseTop(BaseModel):
    enterpriseId: str
    enterpriseName: str
    industry: str
    year: int
    totalEmissionTons: float


class DashboardIndustryShare(BaseModel):
    industry: str
    totalEmissionTons: float
    percent: float


class DashboardRecentUpdate(BaseModel):
    id: str
    enterpriseId: str
    enterpriseName: str
    year: int
    metricCode: str
    metricName: str
    value: float
    unit: str
    operatorName: str
    updatedAt: str


class DashboardSummary(BaseModel):
    meta: DashboardMeta
    kpis: DashboardKpis
    yearly: list[DashboardYearly]
    enterpriseTop: list[DashboardEnterpriseTop]
    industryShares: list[DashboardIndustryShare]
    recentUpdates: list[DashboardRecentUpdate]
