CANONICAL_SUPERADMIN_USERNAME = "super@admin.com"
ALLOWED_ROLES = {"user", "admin", "superadmin"}


def is_canonical_superadmin(user) -> bool:
    return user.username.casefold() == CANONICAL_SUPERADMIN_USERNAME


def validate_superadmin_username(username: str) -> str:
    if username.casefold() != CANONICAL_SUPERADMIN_USERNAME:
        raise ValueError("Only super@admin.com may be Superadmin")
    return CANONICAL_SUPERADMIN_USERNAME


def validate_role_change(current_user, target_user, new_role: str) -> str:
    if new_role not in ALLOWED_ROLES:
        raise ValueError("Invalid role")

    if is_canonical_superadmin(target_user):
        if new_role != "superadmin":
            raise ValueError("Cannot change the canonical superadmin role")
    elif new_role == "superadmin":
        raise ValueError("Only the canonical superadmin may have this role")

    if current_user.role != "superadmin":
        if target_user.role == "superadmin":
            raise ValueError("Cannot modify Superadmin")
        if new_role == "superadmin":
            raise ValueError("Cannot promote to Superadmin")

    return new_role


def can_delete_user(current_user, target_user) -> bool:
    return (
        not is_canonical_superadmin(target_user)
        and target_user.id != current_user.id
    )