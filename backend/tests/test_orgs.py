"""The organisation: the id itself, the paths it owns, and the caches it owns.

This is the plumbing under multi-tenancy, so the tests are about two things
and nothing else: a second organisation is genuinely separate, and one
organisation behaves exactly as this backend did before the idea existed.
"""
from __future__ import annotations

import pytest

from agent.config import Settings
from agent.orgs import (
    DEFAULT_ORG_ID,
    InvalidOrgId,
    current_org_id,
    normalize_org_id,
    reset_org,
    use_org,
)
from agent.voice.context import CallContext

OTHER_ORG = "clinica-sagasta"


def _settings(tmp_path, **overrides) -> Settings:
    return Settings(_env_file=None, data_dir=str(tmp_path), **overrides)


# ---- the id --------------------------------------------------------------
def test_no_organisation_means_the_one_this_backend_was_built_for():
    assert normalize_org_id(None) == DEFAULT_ORG_ID
    assert normalize_org_id("") == DEFAULT_ORG_ID
    assert normalize_org_id("   ") == DEFAULT_ORG_ID


def test_an_id_is_folded_so_two_spellings_are_one_organisation():
    assert normalize_org_id(" Clinica-Arenal ") == DEFAULT_ORG_ID


@pytest.mark.parametrize(
    "raw",
    ["../etc", "a/b", ".hidden", "org id", "ñandú", "-leading", "x" * 64, "/absolute"],
)
def test_an_id_that_could_leave_the_volume_is_refused(raw):
    """It becomes a directory name under DATA_DIR. There is no second chance."""
    with pytest.raises(InvalidOrgId):
        normalize_org_id(raw)


def test_the_current_organisation_is_the_default_until_a_call_binds_one():
    assert current_org_id() == DEFAULT_ORG_ID
    token = use_org(OTHER_ORG)
    try:
        assert current_org_id() == OTHER_ORG
    finally:
        reset_org(token)
    assert current_org_id() == DEFAULT_ORG_ID


# ---- trace paths ---------------------------------------------------------
def test_a_call_writes_its_trace_under_its_own_organisation(tmp_path):
    ctx = CallContext(org_id=OTHER_ORG, data_dir=str(tmp_path), call_id="CA-1")
    assert (tmp_path / OTHER_ORG / "calls" / "CA-1.jsonl").exists()
    assert not (tmp_path / DEFAULT_ORG_ID / "calls").exists()
    assert ctx.org_id == OTHER_ORG


def test_two_organisations_never_write_into_the_same_directory(tmp_path):
    """Two organisations sharing a call directory are two truths on one disk."""
    a = CallContext(org_id=DEFAULT_ORG_ID, data_dir=str(tmp_path), call_id="CA-same")
    b = CallContext(org_id=OTHER_ORG, data_dir=str(tmp_path), call_id="CA-same")
    a.audit("only_a", {})
    b.audit("only_b", {})
    assert "only_a" in (tmp_path / DEFAULT_ORG_ID / "calls" / "CA-same.jsonl").read_text()
    assert "only_b" not in (tmp_path / DEFAULT_ORG_ID / "calls" / "CA-same.jsonl").read_text()


def test_binding_the_harness_call_id_keeps_the_trace_in_its_organisation(tmp_path):
    ctx = CallContext(org_id=OTHER_ORG, data_dir=str(tmp_path))
    provisional = ctx.call_id
    ctx.set_call_id("CA-real")
    assert (tmp_path / OTHER_ORG / "calls" / "CA-real.jsonl").exists()
    assert not (tmp_path / OTHER_ORG / "calls" / f"{provisional}.jsonl").exists()


def test_a_call_says_which_organisation_it_belonged_to(tmp_path):
    """The trace is the only record; an org-less one cannot be attributed."""
    ctx = CallContext(org_id=OTHER_ORG, data_dir=str(tmp_path), call_id="CA-2")
    blob = (tmp_path / OTHER_ORG / "calls" / "CA-2.jsonl").read_text(encoding="utf-8")
    assert f'"org_id": "{OTHER_ORG}"' in blob
    assert ctx.org_id == OTHER_ORG


def test_an_org_id_that_could_walk_out_of_the_volume_never_creates_a_directory(tmp_path):
    with pytest.raises(InvalidOrgId):
        CallContext(org_id="../../etc", data_dir=str(tmp_path), call_id="CA-3")
    assert not (tmp_path / ".." / ".." / "etc").exists()


# ---- reading what is already on disk --------------------------------------
def test_the_traces_recorded_before_organisations_are_still_read(tmp_path):
    """190-odd scored calls sit in DATA_DIR/calls. Losing them is not an option."""
    config = _settings(tmp_path)
    legacy = tmp_path / "calls"
    legacy.mkdir()
    (legacy / "old.jsonl").write_text("{}\n", encoding="utf-8")
    CallContext(data_dir=str(tmp_path), call_id="new")

    names = {p.name for p in config.call_trace_paths()}
    assert names == {"old.jsonl", "new.jsonl"}
    assert config.call_trace_path("old").parent == legacy
    assert config.call_trace_path("new").parent == tmp_path / DEFAULT_ORG_ID / "calls"


def test_nothing_is_ever_written_to_the_old_layout_again(tmp_path):
    config = _settings(tmp_path)
    CallContext(data_dir=str(tmp_path), call_id="new")
    assert not (tmp_path / "calls").exists()
    assert config.calls_dir == str(tmp_path / DEFAULT_ORG_ID / "calls")


def test_a_second_organisation_does_not_inherit_the_old_clinic_traces(tmp_path):
    """The old directory belongs to the clinic that wrote it, not to everyone."""
    config = _settings(tmp_path)
    legacy = tmp_path / "calls"
    legacy.mkdir()
    (legacy / "old.jsonl").write_text("{}\n", encoding="utf-8")
    assert config.call_trace_paths(OTHER_ORG) == []


def test_the_same_call_id_in_both_layouts_is_read_once_from_the_new_one(tmp_path):
    config = _settings(tmp_path)
    legacy = tmp_path / "calls"
    legacy.mkdir()
    (legacy / "CA-dup.jsonl").write_text("{}\n", encoding="utf-8")
    CallContext(data_dir=str(tmp_path), call_id="CA-dup")

    paths = config.call_trace_paths()
    assert len(paths) == 1
    assert paths[0].parent == tmp_path / DEFAULT_ORG_ID / "calls"
    assert config.call_trace_path("CA-dup").parent == tmp_path / DEFAULT_ORG_ID / "calls"


def test_an_unknown_call_resolves_to_the_path_we_would_write(tmp_path):
    config = _settings(tmp_path)
    path = config.call_trace_path("CA-missing", OTHER_ORG)
    assert path == tmp_path / OTHER_ORG / "calls" / "CA-missing.jsonl"
    assert not path.exists()


def test_a_settings_org_id_that_is_not_a_directory_name_fails_at_boot(tmp_path):
    with pytest.raises(ValueError, match="invalid organisation id"):
        _settings(tmp_path, org_id="../elsewhere")
