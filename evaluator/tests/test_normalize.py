"""Normalization table tests - mirror docs/prosper/normalization.md."""
from __future__ import annotations

import pytest

from evaluator.normalize import (
    fold,
    national_id_check_ok,
    norm_email,
    norm_enum,
    norm_national_id,
    norm_person_name,
    norm_phone,
    norm_slot,
    norm_surnames,
)


class TestFold:
    def test_strips_accents(self):
        assert fold("Sánchez") == "sanchez"

    def test_strips_combining_marks(self):
        # 'é' as e + combining acute still folds to 'e'.
        assert fold("e\u0301") == "e"

    def test_case_folds(self):
        assert fold("MARTA") == "marta"

    def test_enye_folds_to_n(self):
        assert fold("Ibañez") == "ibanez"


class TestNationalId:
    def test_drops_dash(self):
        assert norm_national_id("12345678-Z") == "12345678Z"

    def test_drops_spaces(self):
        assert norm_national_id(" 12345678 Z ") == "12345678Z"

    def test_uppercases(self):
        assert norm_national_id("x-1234567-l") == "X1234567L"

    def test_check_letter_valid_dni(self):
        assert national_id_check_ok("12345678Z")
        assert national_id_check_ok("12345678-z")

    def test_check_letter_invalid_dni(self):
        assert not national_id_check_ok("12345678A")

    def test_check_letter_valid_nie(self):
        # X→0: 1234567 % 23 → 'L'
        assert national_id_check_ok("X1234567L")

    def test_check_letter_invalid_nie(self):
        assert not national_id_check_ok("X1234567Z")

    def test_check_letter_garbage(self):
        assert not national_id_check_ok("")
        assert not national_id_check_ok("Z")
        assert not national_id_check_ok("1234567")


class TestPersonName:
    def test_case_and_accents(self):
        assert norm_person_name("  Márta  RUIZ ") == "marta ruiz"

    def test_collapses_whitespace(self):
        assert norm_person_name("Ana   María") == "ana maria"


class TestSurnames:
    def test_order_insensitive(self):
        assert norm_surnames("Gómez Ruiz") == norm_surnames("ruiz gómez")

    def test_different_surnames_differ(self):
        assert norm_surnames("Ruiz") != norm_surnames("Gómez")


class TestPhone:
    def test_national_nine_digits(self):
        assert norm_phone("612345678") == "612345678"

    def test_country_prefix_34(self):
        assert norm_phone("+34 612 345 678") == "612345678"

    def test_country_prefix_0034(self):
        assert norm_phone("0034-612345678") == "612345678"

    def test_punctuation(self):
        assert norm_phone("(612) 345-678") == "612345678"


class TestEmail:
    def test_case_and_whitespace(self):
        assert norm_email("  Marta@Example.COM ") == "marta@example.com"


class TestSlot:
    def test_converts_to_madrid(self):
        assert norm_slot("2026-09-21T07:00:00+00:00") == "2026-09-21T09:00:00+02:00"

    def test_truncates_seconds(self):
        assert norm_slot("2026-09-21T09:00:37+02:00") == "2026-09-21T09:00:00+02:00"

    def test_rejects_naive(self):
        with pytest.raises(ValueError):
            norm_slot("2026-09-21T09:00:00")


class TestEnum:
    def test_folded_lowercase(self):
        assert norm_enum(" Patient_Not_Found ") == "patient_not_found"

    def test_accented_reason(self):
        assert norm_enum("Médico de baja") == "medico_de_baja"
