"""Demo credential file is stable, complete and never echoed on errors."""

from pathlib import Path

import pytest
from firstlook.demo_credentials import demo_labels, load_demo_credentials


def test_demo_credential_labels_are_distinct_per_role_and_table(tmp_path: Path) -> None:
    labels = demo_labels(2)
    file = tmp_path / "demo_credentials"
    file.write_text(
        "\n".join(f"{label}\t{index + 1:024x}" for index, label in enumerate(labels)) + "\n",
        encoding="utf-8",
    )

    credentials = load_demo_credentials(file, 2)

    assert set(credentials) == set(labels)
    assert credentials["patient_anna"].email == "anna.demo@firstlook-hy-demo.duckdns.org"
    assert credentials["responder_2"].email == "responder.t2@firstlook-hy-demo.duckdns.org"
    assert credentials["ed_staff_2"].email == "ed.t2@firstlook-hy-demo.duckdns.org"
    assert len({item.password for item in credentials.values()}) == len(labels)


def test_demo_credential_file_rejects_missing_or_reused_password(tmp_path: Path) -> None:
    file = tmp_path / "demo_credentials"
    file.write_text("patient_anna\taaaaaaaaaaaaaaaaaaaaaaaa\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not match judge tables"):
        load_demo_credentials(file, 1)

    file.write_text(
        "\n".join(f"{label}\taaaaaaaaaaaaaaaaaaaaaaaa" for label in demo_labels(1)),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="invalid demo credential secret") as error:
        load_demo_credentials(file, 1)
    assert "aaaaaaaa" not in str(error.value)
