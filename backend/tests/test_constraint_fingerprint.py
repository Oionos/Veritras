import copy

import pytest

from compare_recovery import compare, summarize_differences
from constraint_fingerprint import NORMALIZATION, canonical_constraint

SOURCE = "CHECK (status::text = ANY (ARRAY['draft'::character varying, 'indexed'::character varying]::text[]))"
RESTORED = "CHECK (status::text = ANY (ARRAY['draft'::character varying::text, 'indexed'::character varying::text]))"


def test_pg_dump_literal_varchar_array_cast_has_one_canonical_form():
    normalized = canonical_constraint(SOURCE)
    assert isinstance(normalized, dict)
    assert normalized == canonical_constraint(RESTORED)
    assert normalized["normalization"] == NORMALIZATION


@pytest.mark.parametrize("changed", [
    RESTORED.replace("'indexed'", "'replaced'"),
    RESTORED.replace("status::", "operation::"),
    RESTORED.replace("= ANY", "<> ANY"),
    RESTORED.replace("= ANY", "= ALL"),
    RESTORED + " NOT VALID",
    RESTORED + " NO INHERIT",
])
def test_changed_constraint_semantics_and_flags_remain_different(changed):
    assert canonical_constraint(SOURCE) != canonical_constraint(changed)


@pytest.mark.parametrize("definition", [
    "PRIMARY KEY (id)", "FOREIGN KEY (id) REFERENCES public.products(id)",
    "CHECK (status IN ('draft','indexed'))", "CHECK (broken syntax!@)",
    SOURCE.replace("character varying", "character varying(3)"),
    SOURCE.replace("character varying", "public.status_domain"),
    SOURCE.replace("'draft'::character varying", "lower('draft')::character varying"),
    SOURCE.replace("'draft'::character varying", "NULL::character varying"),
    "CHECK (note = 'ARRAY[''draft''::character varying]::text[]')",
])
def test_unrecognized_or_nonliteral_casts_keep_the_original_strict_definition(definition):
    assert canonical_constraint(definition) == definition


def test_quoted_literal_contents_are_parsed_as_data_and_never_rewritten_as_sql():
    value = "O''Brien, ARRAY[''other''] /* literal text */"
    source = SOURCE.replace("'indexed'", "'" + value + "'")
    restored = RESTORED.replace("'indexed'", "'" + value + "'")
    assert canonical_constraint(source) == canonical_constraint(restored)
    assert canonical_constraint(source) != canonical_constraint(restored.replace("Brien", "Brian"))


def test_surrounding_predicates_survive_normalization():
    source = SOURCE[:-1] + " AND hours >= 0.25)"
    restored = RESTORED[:-1] + " AND hours >= 0.25)"
    assert canonical_constraint(source) == canonical_constraint(restored)
    assert canonical_constraint(source) != canonical_constraint(restored.replace("0.25", "0.5"))


def test_fingerprint_versions_cannot_be_mixed_with_legacy_snapshots():
    current = {"normalization": "complete_rows", "constraint_normalization": NORMALIZATION,
               "tables": {}, "schema": {}, "sequence_state": {}, "effective_table_access": "same"}
    legacy = copy.deepcopy(current)
    legacy.pop("constraint_normalization")
    result = compare(current, legacy)
    assert result == {"matches": False, "differences": [{"section": "constraint_normalization"}]}
    assert summarize_differences(result)["sections"] == {"constraint_normalization": 1}
