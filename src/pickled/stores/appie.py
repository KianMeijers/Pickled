"""The Appie mobile API, which both AH Deals and AH regular prices are read from (ADR 0005)."""

import httpx

API = "https://api.ah.nl"
# The headers the Appie iOS app sends; the User-Agent comes from `make_client`.
APP_HEADERS = {
    "x-application": "AHWEBSHOP",
    "x-client-name": "appie-ios",
    "x-client-version": "9.28",
    "Accept": "application/json",
}


def anonymous_headers(client: httpx.Client) -> dict[str, str]:
    """The app's headers with a fresh anonymous token, which costs one request."""
    token = client.post(
        f"{API}/mobile-auth/v1/auth/token/anonymous",
        json={"clientId": "appie-ios"},
        headers=APP_HEADERS,
    )
    token.raise_for_status()
    return APP_HEADERS | {"Authorization": f"Bearer {token.json()['access_token']}"}
