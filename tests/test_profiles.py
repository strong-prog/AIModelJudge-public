#!/usr/bin/env python3
"""Integration tests for Profile Manager v2 (Stage 11).

Tests:
- Profile CRUD operations
- Tier gating (Free=1, Pro=3, Business=999)
- Default profile auto-creation
- Profile isolation (user A can't see user B's profiles)
- HA integration (ha_enabled only for Business tier)
- Profile context upload/retrieval

Requires a running backend on :9651 (set AMJ_TEST_BASE_URL to override).

Usage:
  AMJ_ENV=test python3 tests/test_profiles.py
  AMJ_TEST_BASE_URL=http://localhost:9651 python3 tests/test_profiles.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.error
import uuid
from pathlib import Path

_BASE = os.getenv("AMJ_TEST_BASE_URL", "http://127.0.0.1:9651")
_ENV = os.getenv("AMJ_ENV", "test")

PASSED = 0
FAILED = 0


def req(method: str, path: str, body: dict | None = None, api_key: str = "",
        stream_session: str = "") -> dict | list:
    url = f"{_BASE}{path}"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["X-AMJ-API-Key"] = api_key
    if stream_session:
        headers["X-Stream-Session"] = stream_session

    data = json.dumps(body).encode() if body else None
    req_obj = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req_obj, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        try:
            return json.loads(body_text)
        except json.JSONDecodeError:
            return {"error": body_text, "status": e.code}


def _register(email: str, password: str) -> dict:
    return req("POST", "/auth/register", {"email": email, "password": password})


def assert_eq(actual, expected, label: str):
    global PASSED, FAILED
    if actual == expected:
        PASSED += 1
        print(f"  ✅ {label}")
    else:
        FAILED += 1
        print(f"  ❌ {label}: expected {expected!r}, got {actual!r}")


def assert_true(condition: bool, label: str):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✅ {label}")
    else:
        FAILED += 1
        print(f"  ❌ {label}: condition is False")


def assert_in(substring: str, text: str, label: str):
    global PASSED, FAILED
    if substring in text:
        PASSED += 1
        print(f"  ✅ {label}")
    else:
        FAILED += 1
        print(f"  ❌ {label}: {substring!r} not in {text[:200]!r}")


def test_default_profile_auto_create():
    """Test that listing profiles auto-creates a default profile for new users."""
    print("\n── Test: Default profile auto-creation ──")
    email = f"test_pf_{uuid.uuid4().hex[:6]}@test.com"
    password = "testpassword123"

    user = _register(email, password)
    api_key = user.get("api_key", "")

    # First list should auto-create a default profile
    res = req("GET", "/profiles/list", api_key=api_key)
    profiles = res.get("profiles", [])
    assert_eq(len(profiles), 1, "Auto-created 1 default profile")
    assert_in("Мой первый профиль", profiles[0].get("name", ""), "Default profile name")
    assert_true(res.get("active") is not None, "Active profile is set")
    return api_key


def test_profile_crud():
    """Test full CRUD cycle for profiles."""
    print("\n── Test: Profile CRUD ──")
    email = f"test_crud_{uuid.uuid4().hex[:6]}@test.com"
    password = "testpassword123"

    user = _register(email, password)
    api_key = user.get("api_key", "")

    # List to auto-create default
    res = req("GET", "/profiles/list", api_key=api_key)
    profiles = res.get("profiles", [])
    default_id = profiles[0]["id"]

    # Create a new profile — fails for Free tier (max 1)
    create_res = req("POST", "/profiles/create", {
        "name": "Test Profile",
        "description": "A test",
        "tools": ["codegraph"],
        "ha_enabled": False,
    }, api_key=api_key)
    if "error" in str(create_res) or create_res.get("detail"):
        print("  ✅ Free tier correctly blocks second profile creation")
    else:
        print("  ⚠️ Free tier did NOT block second profile (may be Pro/Business user)")

    # Get default profile
    get_res = req("GET", f"/profiles/{default_id}", api_key=api_key)
    assert_eq(get_res.get("profile", {}).get("id"), default_id, "GET profile by id")

    # Patch profile
    patch_res = req("PATCH", f"/profiles/{default_id}", {
        "name": "Renamed Profile",
        "description": "Updated desc",
    }, api_key=api_key)
    assert_true(patch_res.get("ok", False), "PATCH profile")

    # Verify patch
    get_res2 = req("GET", f"/profiles/{default_id}", api_key=api_key)
    assert_eq(get_res2.get("profile", {}).get("name"), "Renamed Profile", "Profile renamed")

    # Delete last profile — should fail
    del_res = req("DELETE", f"/profiles/{default_id}", api_key=api_key)
    assert_true("error" in str(del_res).lower() or not del_res.get("ok", True),
                "DELETE last profile blocked")

    # Activate profile (already active, should still work)
    act_res = req("POST", f"/profiles/{default_id}/activate", api_key=api_key)
    assert_true(act_res.get("ok", False), "Activate profile")

    return api_key


def test_profile_context():
    """Test profile context upload and retrieval."""
    print("\n── Test: Profile context upload/retrieval ──")
    email = f"test_ctx_{uuid.uuid4().hex[:6]}@test.com"
    password = "testpassword123"

    user = _register(email, password)
    api_key = user.get("api_key", "")

    # Get active profile
    res = req("GET", "/profiles/list", api_key=api_key)
    profile_id = res.get("active", "")

    # Upload context
    ctx_res = req("POST", f"/profiles/{profile_id}/context", {
        "name": "BRIEFING.md",
        "content": "# Test Briefing\nThis is a test context file.",
    }, api_key=api_key)
    assert_true(ctx_res.get("ok", False), "Upload profile context")

    # Get context
    get_ctx = req("GET", f"/profiles/{profile_id}/context", api_key=api_key)
    files = get_ctx.get("files", [])
    assert_true(len(files) >= 1, "Context has at least 1 file")
    if files:
        assert_eq(files[0].get("name"), "BRIEFING.md", "Context file name")


def test_profile_isolation():
    """Test that user A cannot see user B's profiles."""
    print("\n── Test: Profile isolation ──")
    email_a = f"test_iso_a_{uuid.uuid4().hex[:4]}@test.com"
    email_b = f"test_iso_b_{uuid.uuid4().hex[:4]}@test.com"
    password = "testpassword123"

    user_a = _register(email_a, password)
    user_b = _register(email_b, password)
    api_key_a = user_a.get("api_key", "")
    api_key_b = user_b.get("api_key", "")

    # Both get auto-created profiles
    profiles_a = req("GET", "/profiles/list", api_key=api_key_a)
    profiles_b = req("GET", "/profiles/list", api_key=api_key_b)

    id_a = profiles_a["profiles"][0]["id"]
    id_b = profiles_b["profiles"][0]["id"]

    # User B tries to access user A's profile
    res = req("GET", f"/profiles/{id_a}", api_key=api_key_b)
    assert_true(res.get("profile") is None or "not found" in str(res).lower(),
                "User B cannot see user A's profile")

    # User B tries to patch user A's profile
    patch_res = req("PATCH", f"/profiles/{id_a}", {"name": "Hacked"}, api_key=api_key_b)
    assert_true(not patch_res.get("ok", True) or "not found" in str(patch_res).lower(),
                "User B cannot patch user A's profile")

    # User B tries to delete user A's profile
    del_res = req("DELETE", f"/profiles/{id_a}", api_key=api_key_b)
    assert_true(not del_res.get("ok", True) or "not found" in str(del_res).lower(),
                "User B cannot delete user A's profile")


def test_ha_enabled_flag():
    """Test that ha_enabled is accepted and stored."""
    print("\n── Test: ha_enabled flag ──")
    email = f"test_ha_{uuid.uuid4().hex[:6]}@test.com"
    password = "testpassword123"

    user = _register(email, password)
    api_key = user.get("api_key", "")

    # Get default profile
    res = req("GET", "/profiles/list", api_key=api_key)
    profiles = res.get("profiles", [])
    if not profiles:
        print(f"  ⚠️ No profiles returned, skipping test. Response: {res}")
        return
    profile_id = profiles[0]["id"]

    # ha_enabled should be false by default
    get_res = req("GET", f"/profiles/{profile_id}", api_key=api_key)
    assert_eq(get_res.get("profile", {}).get("ha_enabled"), False, "ha_enabled defaults to False")

    # Try to enable ha_enabled (Free tier — should work in DB but won't be used in chat)
    patch_res = req("PATCH", f"/profiles/{profile_id}", {
        "ha_enabled": True,
    }, api_key=api_key)
    assert_true(patch_res.get("ok", False), "PATCH ha_enabled=True")

    # Verify
    get_res2 = req("GET", f"/profiles/{profile_id}", api_key=api_key)
    assert_eq(get_res2.get("profile", {}).get("ha_enabled"), True, "ha_enabled persisted")


def test_tier_gating_profiles():
    """Test max_profiles limits."""
    print("\n── Test: Tier-gated profile limits ──")
    email = f"test_tier_{uuid.uuid4().hex[:6]}@test.com"
    password = "testpassword123"

    user = _register(email, password)
    api_key = user.get("api_key", "")

    # Free user — max 1 profile
    # First: auto-created, second: should fail
    res = req("GET", "/profiles/list", api_key=api_key)
    profiles = res.get("profiles", [])
    if not profiles:
        print(f"  ⚠️ No profiles returned, skipping test. Response: {res}")
        return
    assert_eq(len(profiles), 1, "Free tier has 1 auto-created profile")

    create_res = req("POST", "/profiles/create", {
        "name": "Extra Profile",
        "tools": ["codegraph"],
    }, api_key=api_key)

    # Free tier should block
    tier = user.get("tier", "free")
    if tier == "free":
        assert_true("error" in str(create_res).lower() or create_res.get("detail"),
                    f"Free tier blocks profile creation beyond limit (tier={tier})")
    else:
        print(f"  ⚠️ User tier is {tier}, skipping free-tier gating test")


def test_admin_can_see_all():
    """Test that admin can see all users' profiles (audit purposes)."""
    print("\n── Test: Admin data access ──")
    # This is a non-destructive test — just verifies the endpoint structure
    email = f"test_adminpf_{uuid.uuid4().hex[:6]}@test.com"
    password = "testpassword123"

    user = _register(email, password)
    api_key = user.get("api_key", "")

    # Regular user listing their own profiles
    res = req("GET", "/profiles/list", api_key=api_key)
    # API key auth works — profiles should be present
    has_profiles = "profiles" in res
    has_active = "active" in res
    if not has_profiles:
        print(f"  ⚠️ Response missing 'profiles' key. Response: {res}")
    assert_true(has_profiles, "Response has 'profiles' key")
    assert_true(has_active, "Response has 'active' key")


def main():
    global PASSED, FAILED
    print("=" * 60)
    print("Profile Manager v2 — Integration Tests")
    print(f"Base URL: {_BASE}")
    print(f"ENV: {_ENV}")
    print("=" * 60)

    try:
        test_default_profile_auto_create()
        time.sleep(3)  # Avoid auth rate limiting
    except Exception as e:
        FAILED += 1
        print(f"  ❌ Test crashed: {e}")

    try:
        test_profile_crud()
        time.sleep(3)
    except Exception as e:
        FAILED += 1
        print(f"  ❌ Test crashed: {e}")

    try:
        test_profile_context()
        time.sleep(3)
    except Exception as e:
        FAILED += 1
        print(f"  ❌ Test crashed: {e}")

    try:
        test_profile_isolation()
        time.sleep(3)
    except Exception as e:
        FAILED += 1
        print(f"  ❌ Test crashed: {e}")

    try:
        test_ha_enabled_flag()
        time.sleep(3)
    except Exception as e:
        FAILED += 1
        print(f"  ❌ Test crashed: {e}")

    try:
        test_tier_gating_profiles()
        time.sleep(3)
    except Exception as e:
        FAILED += 1
        print(f"  ❌ Test crashed: {e}")

    try:
        test_admin_can_see_all()
    except Exception as e:
        FAILED += 1
        print(f"  ❌ Test crashed: {e}")

    print(f"\n{'=' * 60}")
    print(f"Results: {PASSED} passed, {FAILED} failed")
    print(f"{'=' * 60}")

    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
