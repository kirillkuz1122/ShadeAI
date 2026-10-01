PLACEHOLDER_KEYS = frozenset({"", "change-me", "change-me-to-long-random-string"})


def validate_api_key(value: str) -> str:
    if value in PLACEHOLDER_KEYS or len(value) < 32:
        raise ValueError("SHADE_API_KEY должен содержать не менее 32 символов")
    if not value.isascii() or any(char.isspace() for char in value):
        raise ValueError("SHADE_API_KEY должен содержать ASCII-символы без пробелов")
    return value
