"""Authentication (JWT + Google OAuth 2.0) and RBAC user management routes."""

import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from setrem_estagio_canis.core.config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    UPLOAD_DIR,
    google_oauth_configured,
)
from setrem_estagio_canis.core.images import save_resized_webp
from setrem_estagio_canis.core.security import (
    create_access_token,
    decode_access_token,
    verify_password,
)
from setrem_estagio_canis.database.models import Usuario
from setrem_estagio_canis.database.repository import (
    create_or_update_google_user,
    get_user_by_email,
    get_user_by_id,
    preregister_user,
    toggle_user_active,
    update_user_profile,
    update_user_role,
)
from setrem_estagio_canis.database.session import get_db

router = APIRouter(tags=["Autenticacao"])
_MAX_AVATAR_BYTES = 5 * 1024 * 1024


def get_avatar_path(user_id: int) -> Path:
    """Return the disk path where a user's custom avatar is stored."""
    avatars_dir = UPLOAD_DIR / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    return avatars_dir / f"{user_id}.img"


def user_has_custom_avatar(user_id: int) -> bool:
    """Return True if the user has uploaded a custom avatar image."""
    path = get_avatar_path(user_id)
    return path.exists() and path.stat().st_size > 0


def get_current_user_optional(
    request: Request,
    db: Session,
) -> Usuario | None:
    """Resolve the currently logged-in user from the HTTP-only JWT cookie.

    Args:
        request: Incoming FastAPI request.
        db: Active SQLAlchemy database session.

    Returns:
        Usuario instance if authenticated with a valid token, else None.
    """
    token = request.cookies.get("access_token")
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None
    try:
        user_id = int(str(payload["sub"]))
    except ValueError:
        return None
    return get_user_by_id(db, user_id)


def require_active_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> Usuario:
    """FastAPI dependency requiring an active admin or volunteer session.

    Raises:
        HTTPException: 401 when unauthenticated, 403 when inactive or pending.
    """
    user = get_current_user_optional(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Nao autenticado.")
    if not user.ativo or user.role not in {"admin", "voluntario"}:
        raise HTTPException(
            status_code=403,
            detail="Acesso restrito a voluntarios aprovados.",
        )
    return user


def require_admin_user(
    user: Annotated[Usuario, Depends(require_active_user)],
) -> Usuario:
    """FastAPI dependency restricting an endpoint to admin accounts."""
    if user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Apenas administradores podem executar esta acao.",
        )
    return user


def _set_auth_cookie(response: RedirectResponse, user: Usuario) -> RedirectResponse:
    """Attach the signed HTTP-only JWT session cookie to a redirect response."""
    token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role}
    )
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return response


@router.post("/auth/login")
def local_login(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    """Authenticate using email and password when Google OAuth is not configured."""
    if google_oauth_configured():
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(
                url="/login?erro=Utilize+o+botao+Continuar+com+o+Google.",
                status_code=303,
            )
        raise HTTPException(
            status_code=403,
            detail="Login por senha desativado; utilize Google OAuth.",
        )

    user = get_user_by_email(db, email=email)
    if not user or not verify_password(password, user.senha_hash or ""):
        return RedirectResponse(
            url="/login?erro=E-mail+ou+senha+incorretos.",
            status_code=303,
        )

    if not user.ativo:
        return RedirectResponse(
            url="/login?erro=Conta+desativada+pela+coordenacao.",
            status_code=303,
        )

    target_url = "/aguardando-aprovacao" if user.role == "pendente" else "/"
    return _set_auth_cookie(RedirectResponse(url=target_url, status_code=303), user)


@router.get("/auth/logout")
def logout() -> RedirectResponse:
    """Clear the JWT session cookie and redirect to the login page."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="access_token")
    return response


def _exchange_google_code_for_profile(code: str) -> dict[str, object]:
    """Exchange Google OAuth authorization code for OpenID userinfo profile.

    Args:
        code: Authorization code received in the Google OAuth callback.

    Returns:
        Userinfo dictionary containing 'sub', 'email', 'email_verified',
        'name', and 'picture'.

    Raises:
        ValueError: When token exchange or profile retrieval fails.
    """
    token_data = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")

    token_req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(token_req, timeout=10) as resp:
            token_json = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError("Falha ao validar codigo junto ao Google.") from exc

    google_token = str(token_json.get("access_token") or "")
    if not google_token:
        raise ValueError("Google nao retornou um access_token valido.")

    userinfo_req = urllib.request.Request(
        "https://openidconnect.googleapis.com/v1/userinfo",
        headers={"Authorization": f"Bearer {google_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(userinfo_req, timeout=10) as resp_info:
            profile = json.loads(resp_info.read().decode("utf-8"))
            return profile if isinstance(profile, dict) else {}
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError("Falha ao obter dados do perfil Google.") from exc


@router.get("/auth/google/login")
def start_google_login() -> RedirectResponse:
    """Redirect the user to Google's OAuth 2.0 consent screen with CSRF state."""
    if not google_oauth_configured():
        return RedirectResponse(
            url=(
                "/login?erro=Google+OAuth+nao+configurado+no+.env+"
                "(defina+GOOGLE_CLIENT_ID+e+GOOGLE_CLIENT_SECRET)."
            ),
            status_code=303,
        )

    nonce_state = secrets.token_urlsafe(24)
    state_jwt = create_access_token(
        data={"oauth_state": nonce_state},
        expires_delta=timedelta(minutes=10),
    )
    params = urllib.parse.urlencode(
        {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "state": nonce_state,
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    response = RedirectResponse(
        url=f"https://accounts.google.com/o/oauth2/v2/auth?{params}",
        status_code=303,
    )
    response.set_cookie(
        key="oauth_state",
        value=state_jwt,
        httponly=True,
        samesite="lax",
        max_age=600,
    )
    return response


@router.get("/auth/google/callback")
def google_oauth_callback(
    db: Annotated[Session, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth_state: Annotated[str | None, Cookie()] = None,
) -> RedirectResponse:
    """Process Google OAuth callback, verify CSRF state, and issue JWT cookie."""
    if error or not code or not state or not oauth_state:
        return RedirectResponse(
            url="/login?erro=Autenticacao+com+Google+cancelada+ou+invalida.",
            status_code=303,
        )

    payload_state = decode_access_token(oauth_state)
    if not payload_state or payload_state.get("oauth_state") != state:
        return RedirectResponse(
            url="/login?erro=Sessao+OAuth+expirada+ou+invalida+(CSRF).",
            status_code=303,
        )

    try:
        profile = _exchange_google_code_for_profile(code)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/login?erro={urllib.parse.quote(str(exc))}",
            status_code=303,
        )

    google_sub = str(profile.get("sub") or "").strip()
    email = str(profile.get("email") or "").strip().lower()
    email_verified = bool(profile.get("email_verified"))
    nome = str(profile.get("name") or email.split("@")[0]).strip()
    avatar_url = str(profile.get("picture") or "").strip() or None

    if not google_sub or not email or not email_verified:
        return RedirectResponse(
            url="/login?erro=A+conta+Google+precisa+ter+e-mail+verificado.",
            status_code=303,
        )

    user = create_or_update_google_user(
        db=db,
        google_sub=google_sub,
        email=email,
        nome=nome,
        avatar_url=avatar_url,
    )
    if not user.ativo:
        resp_blocked = RedirectResponse(
            url="/login?erro=Conta+desativada+pela+coordenacao.",
            status_code=303,
        )
        resp_blocked.delete_cookie("oauth_state")
        return resp_blocked

    target = "/aguardando-aprovacao" if user.role == "pendente" else "/"
    response = RedirectResponse(url=target, status_code=303)
    response.delete_cookie("oauth_state")
    return _set_auth_cookie(response, user)


@router.post("/admin/usuarios")
def admin_preregister_user(
    admin: Annotated[Usuario, Depends(require_admin_user)],
    db: Annotated[Session, Depends(get_db)],
    nome: Annotated[str, Form()],
    email: Annotated[str, Form()],
    role: Annotated[str, Form()] = "voluntario",
) -> RedirectResponse:
    """Allow an administrator to pre-register an authorized volunteer email."""
    _ = admin
    preregister_user(db, nome=nome, email=email, role=role)
    return RedirectResponse(
        url="/admin/usuarios?ok=Usuario+autorizado", status_code=303
    )


@router.post("/admin/usuarios/{user_id}/papel")
def admin_change_role(
    user_id: int,
    admin: Annotated[Usuario, Depends(require_admin_user)],
    db: Annotated[Session, Depends(get_db)],
    role: Annotated[str, Form()],
) -> RedirectResponse:
    """Update a user's role (approve pending users or change access level)."""
    if user_id == admin.id and role != "admin":
        return RedirectResponse(
            url="/admin/usuarios?erro=Voce+nao+pode+remover+seu+proprio+acesso+admin.",
            status_code=303,
        )
    update_user_role(db, user_id=user_id, role=role)
    return RedirectResponse(
        url="/admin/usuarios?ok=Permissao+atualizada", status_code=303
    )


@router.post("/admin/usuarios/{user_id}/status")
def admin_toggle_status(
    user_id: int,
    admin: Annotated[Usuario, Depends(require_admin_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RedirectResponse:
    """Enable or disable a user account."""
    if user_id == admin.id:
        return RedirectResponse(
            url="/admin/usuarios?erro=Voce+nao+pode+desativar+a+propria+conta.",
            status_code=303,
        )
    toggle_user_active(db, user_id=user_id)
    return RedirectResponse(url="/admin/usuarios?ok=Status+atualizado", status_code=303)


@router.post("/auth/perfil")
async def update_profile(
    user: Annotated[Usuario, Depends(require_active_user)],
    db: Annotated[Session, Depends(get_db)],
    nome: Annotated[str | None, Form()] = None,
    tema: Annotated[str | None, Form()] = None,
    foto: Annotated[UploadFile | None, File()] = None,
) -> RedirectResponse:
    """Update the authenticated user's display name, theme, and optional avatar."""
    update_user_profile(db=db, user=user, nome=nome, tema=tema)

    if foto and foto.filename:
        content = await foto.read(_MAX_AVATAR_BYTES + 1)
        if 0 < len(content) <= _MAX_AVATAR_BYTES:
            dest = get_avatar_path(user.id)
            if not save_resized_webp(content, dest, max_dimension=384, quality=82):
                dest.write_bytes(content)

    return RedirectResponse(
        url="/configuracoes?ok=Perfil+atualizado+com+sucesso",
        status_code=303,
    )


@router.get("/auth/avatar")
def get_user_avatar(
    user: Annotated[Usuario, Depends(require_active_user)],
) -> Response:
    """Serve the authenticated user's uploaded profile image."""
    path = get_avatar_path(user.id)
    if not path.exists() or path.stat().st_size == 0:
        raise HTTPException(status_code=404, detail="Avatar nao cadastrado.")

    return Response(
        content=path.read_bytes(),
        media_type="image/webp",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/auth/avatar/{user_id}")
def get_specific_user_avatar(
    user_id: int,
    user: Annotated[Usuario, Depends(require_active_user)],
) -> Response:
    """Serve a specific user's custom avatar for internal listings."""
    _ = user
    path = get_avatar_path(user_id)
    if not path.exists() or path.stat().st_size == 0:
        raise HTTPException(status_code=404, detail="Avatar nao cadastrado.")

    return Response(
        content=path.read_bytes(),
        media_type="image/webp",
        headers={"Cache-Control": "no-cache"},
    )
