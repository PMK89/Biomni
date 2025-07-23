import msal
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse, PlainTextResponse

from .config import settings

REDIRECT_PATH = "/getAToken"  # This is the path part of the redirect URI
SCOPE = ["User.Read"]

router = APIRouter()

# Lazily initialize the MSAL app to prevent startup errors if config is missing.
# A better approach for production would be a singleton pattern.
def _get_msal_app_and_authority():
    """Reads config and returns an MSAL app instance and the authority URL."""
    # Read settings inside the function to avoid import-time validation
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
    msal_app, _ = _get_msal_app_and_authority()
    # Store the authentication flow details in the session
    flow = msal_app.initiate_auth_code_flow(
        SCOPE,
        redirect_uri=request.url_for("authorized")
    )
    request.session["flow"] = flow
    # Redirect the user to the Microsoft login page
    return RedirectResponse(url=flow["auth_uri"])

@router.get(REDIRECT_PATH, name="authorized")
async def authorized(request: Request):
    msal_app, _ = _get_msal_app_and_authority()
    try:
        # Retrieve the flow from the session and acquire the token
        flow = request.session.pop("flow", {})
        result = msal_app.acquire_token_by_auth_code_flow(
            flow, dict(request.query_params)
        )

        if "error" in result:
            return PlainTextResponse(f"Login failure: {result.get('error_description')}", status_code=400)

        # Store the user details and token in the session
        request.session["user"] = result
        return RedirectResponse(url=request.url_for("root"))
    except ValueError:
        # If something goes wrong, redirect to the login page
        return RedirectResponse(url=request.url_for("login"))

@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    # Get authority dynamically to construct the logout URL
    _, authority = _get_msal_app_and_authority()
    logout_uri = f"{authority}/oauth2/v2.0/logout?post_logout_redirect_uri={request.url_for('root')}"
    return RedirectResponse(url=logout_uri)


async def get_current_user(request: Request):
    """Dependency to get the current user from the session."""
    user = request.session.get("user")
    if not user:
        # In a real app, you might raise an HTTPException here
        # but for Gradio's dependency, returning None is often handled.
        return None
    return user
