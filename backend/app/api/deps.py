"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.core.auth import TenantPrincipal, get_current_tenant

CurrentTenant = Annotated[TenantPrincipal, Depends(get_current_tenant)]
