from meal_planner.config import settings


def main() -> None:
    if settings.anthropic_api_key.get_secret_value():
        print("meal-planner is set up. Anthropic API key found.")
    else:
        print("meal-planner is set up. No API key yet: add ANTHROPIC_API_KEY to .env.")
