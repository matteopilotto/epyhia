import os

from dotenv import load_dotenv

load_dotenv()

_CREDENTIAL_ATTRS = {
    "vercel": "vercel_token",
    "stripe": "stripe_secret_key",
    "smtp": "smtp_host",
    "mailpit": "mailpit_api_url",
    "sink": "sink_token",
    "auth0": "auth0_domain",
}


class CredentialNotConfigured(Exception):
    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(f"credential not configured: {provider}")


class Settings:
    def __init__(self) -> None:
        self.database_url = os.environ.get("DATABASE_URL") or None
        self.test_database_url = os.environ.get("TEST_DATABASE_URL") or None
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY") or None
        self.vercel_token = os.environ.get("VERCEL_TOKEN") or None
        self.stripe_secret_key = os.environ.get("STRIPE_SECRET_KEY") or None
        self.stripe_webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET") or None
        self.smtp_host = os.environ.get("SMTP_HOST") or None
        self.smtp_port = os.environ.get("SMTP_PORT") or None
        self.mailpit_api_url = os.environ.get("MAILPIT_API_URL") or None
        self.sink_base_url = os.environ.get("SINK_BASE_URL") or None
        self.sink_token = os.environ.get("SINK_TOKEN") or None
        self.auth0_domain = os.environ.get("AUTH0_DOMAIN") or None
        self.auth0_audience = os.environ.get("AUTH0_AUDIENCE") or None
        self.run_budget_usd = os.environ.get("RUN_BUDGET_USD") or None
        self.daily_ceiling_usd = os.environ.get("DAILY_CEILING_USD") or None

    def require(self, provider: str) -> str:
        attr = _CREDENTIAL_ATTRS.get(provider, provider)
        value = getattr(self, attr, None)
        if value is None:
            raise CredentialNotConfigured(provider)
        return value


settings = Settings()
