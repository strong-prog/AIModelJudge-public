"""Feature gating. Single default tier with all features enabled."""

DEFAULT_LIMITS: dict[str, int | bool] = {
    "max_side_panels": 2,
    "mcp_access": True,
    "ha_access": True,
    "max_skills": 999,
    "max_cron_jobs": 999,
    "max_profiles": 999,
}


def get_tier_limit(tier: str, feature: str) -> int | bool:
    return DEFAULT_LIMITS.get(feature, False)


def check_model_count(tier: str, requested_side_count: int) -> bool:
    max_sides = get_tier_limit(tier, "max_side_panels")
    return requested_side_count <= max_sides


def clamp_side_models(tier: str, models: list[str]) -> list[str]:
    """Clamp side models to limit. models are side-only (no center)."""
    max_sides = get_tier_limit(tier, "max_side_panels")
    if not isinstance(max_sides, int):
        max_sides = 0
    return models[:max_sides]
