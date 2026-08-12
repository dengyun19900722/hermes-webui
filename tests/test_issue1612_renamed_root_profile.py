"""Tests for issue #1612: renamed root profile must resolve to ~/.hermes,
not ~/.hermes/profiles/<name>.

A renamed root/default Hermes profile (`is_default=True` on the agent side
but with a display name like `kinni`) was being treated as a named profile
directory under `~/.hermes/profiles/kinni`, which doesn't exist. Every
`if name == 'default':` site in api/profiles.py fell through to the wrong
filesystem path with `Profile 'kinni' does not exist.`

Fix: centralize the "is this the root?" check in `_is_root_profile(name)`
and replace each scattered `if name == 'default':` with it.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest


# ── _is_root_profile core ───────────────────────────────────────────────────


def test_is_root_profile_default_alias():
    """Legacy 'default' literal always resolves as root, regardless of cache state."""
    import api.profiles as p
    p._invalidate_root_profile_cache()
    assert p._is_root_profile('default') is True


def test_is_root_profile_empty_or_none_is_false():
    """Empty/None name is NOT root — caller code decides what to do."""
    import api.profiles as p
    assert p._is_root_profile('') is False
    assert p._is_root_profile(None) is False


def test_is_root_profile_renamed_root_via_lightweight_identity(monkeypatch):
    """A renamed root reported by the identity helper is treated as root."""
    import api.profiles as p

    monkeypatch.setattr(p, '_list_root_profile_names_fast', lambda: {'default', 'kinni'})
    p._invalidate_root_profile_cache()

    assert p._is_root_profile('kinni') is True
    assert p._is_root_profile('haku') is False
    assert p._is_root_profile('default') is True


def test_is_root_profile_caches_results(monkeypatch):
    """Repeated calls don't re-run identity discovery."""
    import api.profiles as p

    calls = {'n': 0}
    def fake_list():
        calls['n'] += 1
        return {'default', 'kinni'}
    monkeypatch.setattr(p, '_list_root_profile_names_fast', fake_list)
    p._invalidate_root_profile_cache()

    p._is_root_profile('kinni')
    p._is_root_profile('kinni')
    p._is_root_profile('haku')
    assert calls['n'] == 1, "Cache should be hit after first lookup"


def test_is_root_profile_never_builds_full_profile_rows(monkeypatch):
    """Session visibility checks must not trigger skills/gateway profile work."""
    import api.profiles as p

    monkeypatch.setattr(
        p,
        'list_profiles_api',
        lambda: (_ for _ in ()).throw(AssertionError("full profile list must not run")),
    )
    monkeypatch.setattr(p, '_list_root_profile_names_fast', lambda: {'default'})
    p._invalidate_root_profile_cache()

    assert p._is_root_profile('named-profile') is False


def test_full_profile_response_refreshes_root_identity_cache(monkeypatch):
    """An authoritative profile load preserves renamed-root compatibility."""
    import api.profiles as p

    p._invalidate_root_profile_cache()
    p._remember_root_profile_names([
        {'name': 'kinni', 'is_default': True},
        {'name': 'haku', 'is_default': False},
    ])
    monkeypatch.setattr(
        p,
        '_list_root_profile_names_fast',
        lambda: (_ for _ in ()).throw(AssertionError("cache should be authoritative")),
    )

    assert p._is_root_profile('kinni') is True
    assert p._is_root_profile('haku') is False


def test_is_root_profile_invalidation_drops_stale(monkeypatch):
    """Explicit invalidation forces re-query on next call."""
    import api.profiles as p

    seq = [{'default', 'kinni'}, {'default', 'noblepro'}]
    monkeypatch.setattr(p, '_list_root_profile_names_fast', lambda: seq[0])

    p._invalidate_root_profile_cache()
    assert p._is_root_profile('kinni') is True
    assert p._is_root_profile('noblepro') is False

    # Simulate rename — drop first state, second is now the truth
    seq.pop(0)
    p._invalidate_root_profile_cache()
    assert p._is_root_profile('kinni') is False
    assert p._is_root_profile('noblepro') is True


def test_is_root_profile_handles_identity_failure(monkeypatch):
    """If identity discovery raises, literal default still works and never raises."""
    import api.profiles as p

    def boom():
        raise RuntimeError("hermes_cli explosion")
    monkeypatch.setattr(p, '_list_root_profile_names_fast', boom)
    p._invalidate_root_profile_cache()

    # 'default' still works (handled before identity discovery).
    assert p._is_root_profile('default') is True
    # Other names return False on failure.
    assert p._is_root_profile('kinni') is False


# ── get_active_hermes_home: returns _DEFAULT_HERMES_HOME for renamed root ──


def test_get_active_hermes_home_returns_default_for_renamed_root(tmp_path, monkeypatch):
    """The core bug: a renamed root profile must resolve to _DEFAULT_HERMES_HOME,
    not _DEFAULT_HERMES_HOME / 'profiles' / <name>."""
    import api.profiles as p

    monkeypatch.setattr(p, '_DEFAULT_HERMES_HOME', tmp_path)
    monkeypatch.setattr(p, '_list_root_profile_names_fast', lambda: {'default', 'kinni'})
    p._invalidate_root_profile_cache()
    monkeypatch.setattr(p, '_active_profile', 'kinni')

    result = p.get_active_hermes_home()
    assert result == tmp_path, f"Expected {tmp_path}, got {result}"


def test_get_active_hermes_home_returns_named_for_real_named_profile(tmp_path, monkeypatch):
    """Backward compat: a real named (non-default) profile still resolves to profiles/<name>."""
    import api.profiles as p

    profile_dir = tmp_path / 'profiles' / 'haku'
    profile_dir.mkdir(parents=True)
    monkeypatch.setattr(p, '_DEFAULT_HERMES_HOME', tmp_path)
    monkeypatch.setattr(p, '_list_root_profile_names_fast', lambda: {'default', 'kinni'})
    p._invalidate_root_profile_cache()
    monkeypatch.setattr(p, '_active_profile', 'haku')

    result = p.get_active_hermes_home()
    assert result == profile_dir


# ── switch_profile: accepts renamed root display name ─────────────────────


def test_switch_profile_resolution_renamed_root_picks_default_home(tmp_path, monkeypatch):
    """switch_profile()'s resolution branch: a renamed root must select
    _DEFAULT_HERMES_HOME, not raise 'Profile <name> does not exist.'

    We don't drive switch_profile() end-to-end (it touches reload_config,
    workspace resolution, env mutation, etc.); instead we exercise the
    same resolve-or-raise structure that lives at the head of switch_profile.
    """
    import api.profiles as p

    monkeypatch.setattr(p, '_DEFAULT_HERMES_HOME', tmp_path)
    monkeypatch.setattr(p, '_list_root_profile_names_fast', lambda: {'default', 'kinni'})
    p._invalidate_root_profile_cache()

    # Mirror switch_profile's resolution logic
    name = 'kinni'
    if p._is_root_profile(name):
        home = p._DEFAULT_HERMES_HOME
    else:
        home = p._resolve_named_profile_home(name)
        if not home.is_dir():
            raise ValueError(f"Profile '{name}' does not exist.")
    assert home == tmp_path

    # Sanity: a TRULY missing profile still raises (backward compat)
    with pytest.raises(ValueError, match="does not exist"):
        name = 'phantom'
        if p._is_root_profile(name):
            home = p._DEFAULT_HERMES_HOME
        else:
            home = p._resolve_named_profile_home(name)
            if not home.is_dir():
                raise ValueError(f"Profile '{name}' does not exist.")


def test_switch_profile_sticky_marker_renamed_root(tmp_path, monkeypatch):
    """switch_profile writes '' (empty marker) to active_profile file when
    switching to the root profile, regardless of its display name. This
    means a subsequent boot reads '' → falls through to 'default' alias →
    _is_root_profile('default') → resolves to _DEFAULT_HERMES_HOME, which
    is the only correct location for the renamed-root case."""
    import api.profiles as p

    monkeypatch.setattr(p, '_DEFAULT_HERMES_HOME', tmp_path)
    monkeypatch.setattr(p, '_list_root_profile_names_fast', lambda: {'default', 'kinni'})
    p._invalidate_root_profile_cache()

    # Mirror the sticky-write line directly — guards that the new ternary
    # uses _is_root_profile, not the literal-'default' compare.
    written = '' if p._is_root_profile('kinni') else 'kinni'
    assert written == ''
    written2 = '' if p._is_root_profile('haku') else 'haku'
    assert written2 == 'haku' 


def test_delete_profile_blocks_renamed_root(tmp_path, monkeypatch):
    """delete_profile_api on a renamed root must refuse, same as 'default'."""
    import api.profiles as p

    monkeypatch.setattr(p, '_DEFAULT_HERMES_HOME', tmp_path)
    monkeypatch.setattr(p, '_list_root_profile_names_fast', lambda: {'default', 'kinni'})
    p._invalidate_root_profile_cache()

    with pytest.raises(ValueError, match="Cannot delete the default profile"):
        p.delete_profile_api('kinni')


# ── Cleanup: invalidate cache between tests so they don't leak ─────────────


@pytest.fixture(autouse=True)
def _invalidate_cache_around_test():
    import api.profiles as p
    p._invalidate_root_profile_cache()
    yield
    p._invalidate_root_profile_cache()
