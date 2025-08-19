#!/usr/bin/env python3
"""
Diagnostic script to test Azure AD configuration
"""
import os
from dotenv import load_dotenv
from app.config import settings

# Load environment variables
load_dotenv()

print("=== Azure AD Configuration Diagnostic ===")
print(f"CLIENT_ID: {settings.CLIENT_ID}")
print(f"TENANT_ID: {settings.TENANT_ID}")
print(f"CLIENT_SECRET: {'[SET]' if settings.CLIENT_SECRET else '[MISSING]'}")
print()

print("=== Environment Variables ===")
for key in ['CLIENT_ID', 'CLIENT_SECRET', 'TENANT_ID', 'OPENAI_API_KEY', 'OPENAI_ENDPOINT']:
    value = os.getenv(key)
    print(f"{key}: {'[SET]' if value else '[MISSING]'}")

print()
print("=== Expected Redirect URI ===")
print("http://localhost:8000/getAToken")
print()
print("=== Azure Portal Checklist ===")
print("1. Go to Azure Portal → Azure Active Directory → App registrations")
print("2. Find your app and check:")
print("   - Redirect URIs: http://localhost:8000/getAToken")
print("   - Platform: Web")
print("   - Implicit grant: Access tokens and ID tokens should be UNCHECKED")
print("   - API permissions: Microsoft Graph → User.Read granted")
