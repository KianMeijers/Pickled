from pickle_app.config import settings


def main() -> None:
    if settings.anthropic_api_key.get_secret_value():
        print("Pickle is set up. Anthropic API key found.")
    else:
        print("Pickle is set up. No API key yet: add ANTHROPIC_API_KEY to .env.")
