from datetime import date
from pathlib import Path

import pytest

from evaluator.clinic.dataset import Dataset

DATASET = Path(__file__).resolve().parents[1] / "data/clinic_dataset.json"


@pytest.mark.parametrize(
    ("specialty", "patient", "expected"),
    [
        ("general", "P00042", "review"),
        ("general", "P00043", "first_visit"),
        ("general", None, "review"),
        ("orthopaedics", "P00043", "ortho_review"),
        ("dermatology", "P00042", "dermatology_review"),
    ],
)
def test_type_is_selected_by_clinic_and_every_slot_agrees(specialty, patient, expected):
    data = Dataset.load(DATASET)
    result = data.availability(
        date(2026, 9, 21), date(2026, 9, 21), specialty_id=specialty, patient_id=patient,
    )
    assert result["appointment_type"]["id"] == expected
    assert all(slot["appointment_type_id"] == expected for slot in result["slots"])
    if specialty == "general":
        assert result["slots"]


def test_provider_selects_specialty_and_empty_day_still_has_type():
    result = Dataset.load(DATASET).availability(
        date(2026, 9, 20), date(2026, 9, 20), provider_id="PR01", patient_id="P00042",
    )
    assert result["slots"] == []
    assert result["appointment_type"]["id"] == "review"


def test_unknown_specialty_is_a_validation_error():
    with pytest.raises(ValueError, match="known provider"):
        Dataset.load(DATASET).availability(
            date(2026, 9, 21), date(2026, 9, 21), specialty_id="invented",
        )
