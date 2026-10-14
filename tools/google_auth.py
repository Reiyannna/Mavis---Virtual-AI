"""Google auth + shared plumbing for the Gmail/Calendar/Drive tool modules."""
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/drive',
]
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
TOKEN_PATH = os.path.join(CONFIG_DIR, 'token.json')
CREDENTIALS_PATH = os.path.join(CONFIG_DIR, 'credentials.json')
_home = os.environ.get('USERPROFILE') or os.path.expanduser('~')
DOWNLOADS_DIR = os.path.join(_home, 'Download')
_services = None

def _needs_reauth(creds):
    """True if the stored token does not cover the widened SCOPES."""
    if not creds or not creds.valid:
        return True
    token_scopes = set(creds.scopes or [])
    return not set(SCOPES).issubset(token_scopes)
def authenticate_google():
    """Handles the OAuth 2.0 login flow using credentials and token stored in the config folder."""
    global _services
    if _services:
        return _services

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token and not _needs_reauth(creds):
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_PATH):
                print(f"Error: Credentials file not found at '{CREDENTIALS_PATH}'.")
                return None, None, None
            if creds:
                print("Google scopes changed - re-running OAuth consent.")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(TOKEN_PATH, 'w') as token_file:
            token_file.write(creds.to_json())

    try:
        _services = (
            build('gmail', 'v1', credentials=creds),
            build('calendar', 'v3', credentials=creds),
            build('drive', 'v3', credentials=creds),
        )
        return _services
    except Exception as e:
        print(f"Error connecting to Google Services: {e}")
        return None, None, None
def _gmail():
    gmail, _, _ = authenticate_google()
    return gmail
def _calendar():
    _, calendar, _ = authenticate_google()
    return calendar
def _drive():
    _, _, drive = authenticate_google()
    return drive
def _as_json(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
def _escape_query(value):
    return value.replace("'", "\\'")
def list_google_accounts() -> str:
    """Returns the Google account email used by all three services (single-account OAuth)."""
    gmail = _gmail()
    if not gmail:
        return "Not connected."
    try:
        profile = gmail.users().getProfile(userId='me').execute()
        return "Connected Google account: " + profile.get('emailAddress', 'unknown')
    except Exception as e:
        return f"Could not read account info: {e}"

__all__ = [
    "authenticate_google",
    "list_google_accounts",
]

if __name__ == '__main__':
    print("Initializing Google OAuth flow...")
    gmail, calendar, drive = authenticate_google()
    if gmail and calendar and drive:
        print("Authentication successful! 'token.json' created/updated in 'config/'.")
