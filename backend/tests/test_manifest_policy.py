import pytest
from firstlook.settings import Settings
from firstlook.sharing.manifest import (
    ManifestFailure,
    ManifestInput,
    _breakglass_reason,
    breakglass_limit_reached,
)
from firstlook.sharing.manifest_router import ManifestBody


def test_breakglass_requires_explicit_acknowledgement_even_for_generic_clients() -> None:
    generic = ManifestInput("Emergency access for patient", None, None, None, False, None)
    with pytest.raises(ManifestFailure) as error:
        _breakglass_reason(generic)
    assert error.value.status == 403
    assert "acknowledgement" in error.value.title
    acknowledged = ManifestInput("Emergency access for patient", None, None, None, True, None)
    assert _breakglass_reason(acknowledged) == "Emergency access for patient"


@pytest.mark.parametrize(
    ("link_count", "ip_count", "link_limit", "ip_limit", "blocked"),
    [
        (2, 9, 3, 10, False),
        (3, 0, 3, 10, True),
        (0, 10, 3, 10, True),
        (49, 99, 50, 100, False),
        (50, 0, 50, 100, True),
        (0, 100, 50, 100, True),
    ],
)
def test_breakglass_limits_are_enforced_at_both_profiles(
    link_count: int, ip_count: int, link_limit: int, ip_limit: int, blocked: bool
) -> None:
    assert breakglass_limit_reached(link_count, ip_count, link_limit, ip_limit) is blocked


def test_production_rejects_demo_limits() -> None:
    with pytest.raises(ValueError):
        Settings(fl_env="production", fl_breakglass_link_limit=50, fl_breakglass_ip_limit=100)


def test_manifest_schema_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        ManifestBody.model_validate({"recipient": "someone", "unexpected": "PHI"})
