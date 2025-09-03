import msal
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, PlainTextResponse

from .config import settings

REDIRECT_PATH = "/getAToken"  # Original redirect path - ensure this matches Azure Portal
SCOPE = ["User.Read"]

router = APIRouter()

# Lazily initialize the MSAL app to prevent startup errors if config is missing.
# A better approach for production would be a singleton pattern.
def _get_msal_app_and_authority():
    """Reads config and returns an MSAL app instance and the authority URL."""
    # Read settings inside the function to avoid import-time validation
    if not settings.AAD_ENABLED:
        raise RuntimeError("AAD not configured for this environment")
    client_id = settings.CLIENT_ID
    client_secret = settings.CLIENT_SECRET
    tenant_id = settings.TENANT_ID
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    
    app = msal.ConfidentialClientApplication(
        client_id, authority=authority, client_credential=client_secret
    )
    return app, authority

@router.get("/login")
async def login(request: Request):
    # In dev mode (no AAD), auto-login a local dev user
    if not settings.AAD_ENABLED:
        dev_user = {
            "name": "Dev User",
            "oid": "anonymous",
            "tid": "dev-tenant",
            "preferred_username": "dev@example.com",
        }
        request.session["user"] = dev_user
        base = (request.scope.get('root_path') or '').rstrip('/')
        root_url = f"{base}/" if base else "/"
        return RedirectResponse(url=root_url)

    msal_app, _ = _get_msal_app_and_authority()
    redirect_uri = str(request.url_for("authorized"))
    print(f"DEBUG: Using redirect URI: {redirect_uri}")
    flow = msal_app.initiate_auth_code_flow(
        SCOPE,
        redirect_uri=redirect_uri
    )
    request.session["flow"] = flow
    return RedirectResponse(url=flow["auth_uri"])

@router.get(REDIRECT_PATH, name="authorized")
async def authorized(request: Request):
    if not settings.AAD_ENABLED:
        return PlainTextResponse("AAD not configured in this environment.", status_code=400)

    msal_app, _ = _get_msal_app_and_authority()
    
    print(f"DEBUG: Authorized endpoint called with query params: {dict(request.query_params)}")
    print(f"DEBUG: Session keys: {list(request.session.keys())}")
    
    # Debug: Check if we have a flow in session
    flow = request.session.pop("flow", None)
    if not flow:
        print("DEBUG: No flow found in session")
        return PlainTextResponse(
            "Authentication error: No session flow found. Please clear cookies and try again.",
            status_code=400
        )
    
    print(f"DEBUG: Found flow in session: {type(flow)}")
    
    try:
        query_params = dict(request.query_params)
        print(f"DEBUG: Processing auth code flow with params: {list(query_params.keys())}")
        
        result = msal_app.acquire_token_by_auth_code_flow(flow, query_params)

        if "error" in result:
            error_desc = result.get('error_description', 'Unknown error')
            print(f"DEBUG: MSAL error: {result.get('error')} - {error_desc}")
            return PlainTextResponse(f"Login failure: {error_desc}", status_code=400)

        print("DEBUG: Authentication successful")
        # Store only minimal user claims to avoid oversized session cookies.
        # Do NOT store full tokens in the client-side session cookie.
        claims = result.get("id_token_claims", {}) if isinstance(result, dict) else {}
        user_min = {
            "name": claims.get("name") or claims.get("preferred_username") or "User",
            "oid": claims.get("oid"),
            "tid": claims.get("tid"),
            "preferred_username": claims.get("preferred_username"),
        }
        request.session["user"] = user_min
        base = (request.scope.get('root_path') or '').rstrip('/')
        root_url = f"{base}/" if base else "/"
        return RedirectResponse(url=root_url)
    except Exception as e:
        print(f"DEBUG: Exception in authorized: {str(e)}")
        return PlainTextResponse(
            f"Authentication error: {str(e)}. Please check Azure AD configuration.",
            status_code=400
        )

@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    if not settings.AAD_ENABLED:
        base = (request.scope.get('root_path') or '').rstrip('/')
        root_url = f"{base}/" if base else "/"
        return RedirectResponse(url=root_url)
    # Get authority dynamically to construct the logout URL
    _, authority = _get_msal_app_and_authority()
    logout_uri = f"{authority}/oauth2/v2.0/logout?post_logout_redirect_uri={request.url_for('root')}"
    return RedirectResponse(url=logout_uri)


def get_current_user(request: Request):
    """Dependency to get the current user from the session.
    Implemented as a synchronous function because Gradio's auth_dependency
    expects a regular callable, not a coroutine.
    """
    user = request.session.get("user")
    if user:
        return user
    # In dev mode, allow an anonymous dev user for local testing
    if not settings.AAD_ENABLED:
        return {"name": "Dev User", "oid": "anonymous", "preferred_username": "dev@example.com"}
    # In production (AAD enabled) with no session, block access
    return None
