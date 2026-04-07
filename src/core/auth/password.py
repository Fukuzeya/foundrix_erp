"""Password policy enforcement.

Validates password strength and enforces configurable complexity rules.
Used during user creation, password change, and password reset flows.
"""

import re

from src.core.errors.exceptions import ValidationError

# ── Policy configuration ─────────────────────────────────────────────
# These can be moved to Settings if you want per-environment overrides.

MIN_LENGTH = 8
MAX_LENGTH = 128
REQUIRE_UPPERCASE = True
REQUIRE_LOWERCASE = True
REQUIRE_DIGIT = True
REQUIRE_SPECIAL = True
SPECIAL_CHARACTERS = r"!@#$%^&*()_+\-=\[\]{}|;':\",./<>?`~"


def validate_password_strength(password: str) -> None:
    """Validate that a password meets the platform's complexity requirements.

    Rules enforced:
    - Minimum and maximum length
    - At least one uppercase letter (if REQUIRE_UPPERCASE)
    - At least one lowercase letter (if REQUIRE_LOWERCASE)
    - At least one digit (if REQUIRE_DIGIT)
    - At least one special character (if REQUIRE_SPECIAL)
    - No leading or trailing whitespace

    Args:
        password: The plaintext password to validate.

    Raises:
        ValidationError: If the password does not meet any requirement.
            The ``details`` field lists all violations at once so the
            user can fix everything in one attempt.
    """
    violations: list[str] = []

    if len(password) < MIN_LENGTH:
        violations.append(f"Must be at least {MIN_LENGTH} characters long")

    if len(password) > MAX_LENGTH:
        violations.append(f"Must be at most {MAX_LENGTH} characters long")

    if password != password.strip():
        violations.append("Must not have leading or trailing whitespace")

    if REQUIRE_UPPERCASE and not re.search(r"[A-Z]", password):
        violations.append("Must contain at least one uppercase letter")

    if REQUIRE_LOWERCASE and not re.search(r"[a-z]", password):
        violations.append("Must contain at least one lowercase letter")

    if REQUIRE_DIGIT and not re.search(r"\d", password):
        violations.append("Must contain at least one digit")

    if REQUIRE_SPECIAL and not re.search(rf"[{re.escape(SPECIAL_CHARACTERS)}]", password):
        violations.append("Must contain at least one special character")

    if violations:
        raise ValidationError(
            message="Password does not meet security requirements",
            details={"violations": violations},
        )
