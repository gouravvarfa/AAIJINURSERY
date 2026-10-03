"""Developer Dashboard: Access Control endpoints -- sessions, login
attempts, admin enable/disable (Phase 2), and Roles/Permissions/per-user
overrides (Phase 3), all in one Developer-only file.

Every endpoint here is gated by Depends(get_current_developer) with no
exceptions -- this is the concrete backend enforcement of "only Developer
can manage Admins/Roles/Sessions" and "Super Access cannot grant itself
more access": Super Access simply has no reachable code path into this
router at all.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.audit import (
    ADMIN_DISABLED,
    ADMIN_ENABLED,
    ALL_SESSIONS_REVOKED,
    PERMISSION_OVERRIDE_GRANTED,
    PERMISSION_OVERRIDE_REVOKED,
    ROLE_CREATED,
    ROLE_DELETED,
    ROLE_PERMISSION_CHANGED,
    ROLE_UPDATED,
    SESSION_REVOKED,
    record_admin_audit,
)
from app.database import get_db
from app.deps import get_current_developer
from app.models import AdminSession, AdminUser, LoginAttempt, Role, RolePermission, UserPermissionOverride
from app.permissions import ACTIONS, MODULES
from app.schemas import (
    AdminSessionOut,
    AdminUserOut,
    LoginAttemptOut,
    PermissionOverrideIn,
    PermissionOverrideOut,
    RoleCreateIn,
    RoleOut,
    RolePermissionOut,
    RoleUpdateIn,
)

router = APIRouter(prefix="/api/admin/rbac", tags=["rbac"])


# ---------- Admin enable / disable ----------


@router.put("/admins/{item_id}/status", response_model=AdminUserOut)
def set_admin_status(
    item_id: int,
    is_active: bool,
    admin: str = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    item = db.query(AdminUser).filter(AdminUser.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Admin not found")
    if item.username == admin and not is_active:
        raise HTTPException(status_code=400, detail="You cannot disable your own account")
    if item.role == "developer" and not is_active:
        remaining = (
            db.query(AdminUser)
            .filter(AdminUser.role == "developer", AdminUser.is_active.is_(True), AdminUser.id != item_id)
            .count()
        )
        if remaining == 0:
            raise HTTPException(status_code=400, detail="Cannot disable the last remaining active developer")

    item.is_active = is_active
    db.commit()
    db.refresh(item)
    record_admin_audit(admin, ADMIN_ENABLED if is_active else ADMIN_DISABLED, {"username": item.username})
    return item


# ---------- Sessions ----------


@router.get("/sessions", response_model=list[AdminSessionOut])
def list_sessions(
    request: Request,
    admin_user_id: int | None = None,
    active_only: bool = True,
    admin: str = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    # Read from this request's own signed cookie -- never trust a
    # client-supplied "this is my current session" claim.
    current_token = request.session.get("admin_session_id")
    query = db.query(AdminSession)
    if admin_user_id is not None:
        query = query.filter(AdminSession.admin_user_id == admin_user_id)
    if active_only:
        query = query.filter(AdminSession.revoked_at.is_(None))
    rows = query.order_by(AdminSession.last_seen_at.desc()).limit(200).all()
    return [
        AdminSessionOut(
            id=r.id,
            username=r.username,
            ip_address=r.ip_address,
            user_agent=r.user_agent,
            created_at=r.created_at,
            last_seen_at=r.last_seen_at,
            revoked_at=r.revoked_at,
            is_current=bool(current_token) and r.session_token == current_token,
        )
        for r in rows
    ]


@router.post("/sessions/{session_id}/revoke")
def revoke_session(session_id: int, admin: str = Depends(get_current_developer), db: Session = Depends(get_db)):
    row = db.query(AdminSession).filter(AdminSession.id == session_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    if row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        row.revoked_by = admin
        row.revoke_reason = "revoked_by_developer"
        db.commit()
        record_admin_audit(admin, SESSION_REVOKED, {"username": row.username, "session_id": session_id})
    return {"ok": True}


@router.post("/users/{item_id}/revoke-all-sessions")
def revoke_all_sessions(item_id: int, admin: str = Depends(get_current_developer), db: Session = Depends(get_db)):
    item = db.query(AdminUser).filter(AdminUser.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Admin not found")
    now = datetime.utcnow()
    rows = (
        db.query(AdminSession)
        .filter(AdminSession.admin_user_id == item_id, AdminSession.revoked_at.is_(None))
        .all()
    )
    for row in rows:
        row.revoked_at = now
        row.revoked_by = admin
        row.revoke_reason = "revoke_all_by_developer"
    db.commit()
    record_admin_audit(admin, ALL_SESSIONS_REVOKED, {"username": item.username, "count": len(rows)})
    return {"ok": True, "revoked_count": len(rows)}


# ---------- Login attempts ----------


@router.get("/login-attempts", response_model=list[LoginAttemptOut])
def list_login_attempts(
    response: Response,
    identifier: str | None = None,
    success: bool | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    admin: str = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    query = db.query(LoginAttempt)
    if identifier:
        query = query.filter(LoginAttempt.identifier.ilike(f"%{identifier}%"))
    if success is not None:
        query = query.filter(LoginAttempt.success == success)

    total = query.count()
    rows = query.order_by(LoginAttempt.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(page)
    response.headers["X-Total-Pages"] = str(max(1, -(-total // limit)))
    return rows


# ---------- Modules / actions catalog ----------


@router.get("/catalog")
def get_catalog(admin: str = Depends(get_current_developer)):
    return {"modules": MODULES, "actions": ACTIONS}


# ---------- Roles & permission matrix ----------


def _role_out(db: Session, role: Role) -> RoleOut:
    user_count = db.query(AdminUser).filter(AdminUser.custom_role_id == role.id).count()
    permissions = db.query(RolePermission).filter(RolePermission.role_id == role.id).all()
    return RoleOut(
        id=role.id,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        created_by=role.created_by,
        created_at=role.created_at,
        updated_at=role.updated_at,
        user_count=user_count,
        permissions=[RolePermissionOut.model_validate(p) for p in permissions],
    )


@router.get("/roles", response_model=list[RoleOut])
def list_roles(admin: str = Depends(get_current_developer), db: Session = Depends(get_db)):
    roles = db.query(Role).order_by(Role.is_system.desc(), Role.name).all()
    return [_role_out(db, r) for r in roles]


@router.post("/roles", response_model=RoleOut, status_code=201)
def create_role(payload: RoleCreateIn, admin: str = Depends(get_current_developer), db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Role name is required")
    if db.query(Role).filter(Role.name == name).first():
        raise HTTPException(status_code=400, detail="A role with this name already exists")
    role = Role(name=name, description=payload.description, is_system=False, created_by=admin)
    db.add(role)
    db.commit()
    db.refresh(role)
    record_admin_audit(admin, ROLE_CREATED, {"role": name})
    return _role_out(db, role)


@router.put("/roles/{role_id}", response_model=RoleOut)
def update_role(
    role_id: int, payload: RoleUpdateIn, admin: str = Depends(get_current_developer), db: Session = Depends(get_db)
):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=400, detail="System roles cannot be modified")

    if payload.name is not None:
        new_name = payload.name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="Role name is required")
        if new_name != role.name and db.query(Role).filter(Role.name == new_name).first():
            raise HTTPException(status_code=400, detail="A role with this name already exists")
        role.name = new_name
    if payload.description is not None:
        role.description = payload.description

    if payload.permissions is not None:
        existing = {rp.module: rp for rp in db.query(RolePermission).filter(RolePermission.role_id == role.id)}
        for entry in payload.permissions:
            if entry.module not in MODULES:
                raise HTTPException(status_code=400, detail=f"Unknown module: {entry.module}")
            row = existing.get(entry.module)
            if not row:
                row = RolePermission(role_id=role.id, module=entry.module)
                db.add(row)
            row.can_view = entry.can_view
            row.can_create = entry.can_create
            row.can_edit = entry.can_edit
            row.can_delete = entry.can_delete
            row.can_export = entry.can_export
            row.can_print = entry.can_print
            row.can_approve = entry.can_approve
            row.can_cancel = entry.can_cancel
        record_admin_audit(admin, ROLE_PERMISSION_CHANGED, {"role": role.name})

    db.commit()
    db.refresh(role)
    record_admin_audit(admin, ROLE_UPDATED, {"role": role.name})
    return _role_out(db, role)


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(role_id: int, admin: str = Depends(get_current_developer), db: Session = Depends(get_db)):
    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=400, detail="System roles cannot be deleted")
    in_use = db.query(AdminUser).filter(AdminUser.custom_role_id == role.id).count()
    if in_use:
        raise HTTPException(status_code=400, detail=f"{in_use} admin(s) are still assigned this role")
    db.delete(role)
    db.commit()
    record_admin_audit(admin, ROLE_DELETED, {"role": role.name})


# ---------- Per-user permission overrides ----------


@router.get("/users/{item_id}/overrides", response_model=list[PermissionOverrideOut])
def list_overrides(item_id: int, admin: str = Depends(get_current_developer), db: Session = Depends(get_db)):
    return (
        db.query(UserPermissionOverride)
        .filter(UserPermissionOverride.admin_user_id == item_id)
        .order_by(UserPermissionOverride.created_at.desc())
        .all()
    )


@router.post("/users/{item_id}/overrides", response_model=PermissionOverrideOut, status_code=201)
def create_override(
    item_id: int,
    payload: PermissionOverrideIn,
    admin: str = Depends(get_current_developer),
    db: Session = Depends(get_db),
):
    item = db.query(AdminUser).filter(AdminUser.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Admin not found")
    if payload.module not in MODULES:
        raise HTTPException(status_code=400, detail=f"Unknown module: {payload.module}")
    if payload.action not in ACTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown action: {payload.action}")
    if payload.effect not in ("ALLOW", "DENY"):
        raise HTTPException(status_code=400, detail="effect must be 'ALLOW' or 'DENY'")

    existing = (
        db.query(UserPermissionOverride)
        .filter(
            UserPermissionOverride.admin_user_id == item_id,
            UserPermissionOverride.module == payload.module,
            UserPermissionOverride.action == payload.action,
        )
        .first()
    )
    if existing:
        db.delete(existing)
        db.flush()

    row = UserPermissionOverride(
        admin_user_id=item_id,
        module=payload.module,
        action=payload.action,
        effect=payload.effect,
        granted_by=admin,
        reason=payload.reason,
        expires_at=payload.expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    record_admin_audit(
        admin,
        PERMISSION_OVERRIDE_GRANTED,
        {"username": item.username, "module": payload.module, "action": payload.action, "effect": payload.effect},
    )
    return row


@router.delete("/users/{item_id}/overrides/{override_id}", status_code=204)
def delete_override(
    item_id: int, override_id: int, admin: str = Depends(get_current_developer), db: Session = Depends(get_db)
):
    row = (
        db.query(UserPermissionOverride)
        .filter(UserPermissionOverride.id == override_id, UserPermissionOverride.admin_user_id == item_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Override not found")
    item = db.query(AdminUser).filter(AdminUser.id == item_id).first()
    db.delete(row)
    db.commit()
    record_admin_audit(
        admin,
        PERMISSION_OVERRIDE_REVOKED,
        {"username": item.username if item else item_id, "module": row.module, "action": row.action},
    )
