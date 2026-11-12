"""Read-only exact note-field lineage checks, not a financial or selection policy.

The caller binds source identities and required field pairs explicitly. This
module neither derives a reason/date/status nor selects an alternate MPN. A clean
correspondence gate is not client acceptance, source authority or release approval.
"""
from collections import defaultdict
from collections.abc import Mapping
import math


def _missing(value):
    return value is None or isinstance(value, str) and not value.strip()


def _scalar(value):
    # Notes are scalar transport values. Dates require an explicit caller format;
    # no object equality, date conversion, NaN or infinity can silently pass.
    return type(value) in (str, int, bool) or type(value) is float and math.isfinite(value)


def _identity(value):
    # Typed scalar keys avoid True==1, 1==1.0 and string/numeric ID aliasing.
    if type(value) not in (str, int) or _missing(value):
        return None
    return (type(value).__name__, value)


def audit_note_lineage(source_rows, output_rows, *, source_id_field,
                       output_source_id_field, field_map):
    """Compare required output values to their explicitly named source row.

    field_map maps source field names to output field names. Every listed field
    is required on both sides and compared by exact Python type and value. Missing
    source values remain blockers, never permission to make them up. No implicit
    CPN-only joins, status categories, date parsing, price tests or default rules.
    """
    if not isinstance(source_rows, (list, tuple)) or not isinstance(output_rows, (list, tuple)):
        raise ValueError('Source and output rows must be explicit lists or tuples')
    if not all(isinstance(k, str) and k.strip() for k in (source_id_field, output_source_id_field)):
        raise ValueError('Explicit nonempty source identity field names required')
    if not isinstance(field_map, Mapping) or not field_map:
        raise ValueError('Explicit nonempty required field map required')
    pairs = tuple(field_map.items())
    if not all(isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip() for k, v in pairs):
        raise ValueError('Required field names must be nonempty strings')
    if len({v for _, v in pairs}) != len(pairs):
        raise ValueError('Each output field must have exactly one source field')
    diagnostics = []
    grouped = defaultdict(list)
    for i, row in enumerate(source_rows):
        if not isinstance(row, Mapping):
            diagnostics.append({'code': 'source_row_not_mapping', 'source_row_index': i})
            continue
        key = _identity(row.get(source_id_field))
        if key is None:
            diagnostics.append({'code': 'source_identity_missing_or_invalid', 'source_row_index': i})
            continue
        grouped[key].append((i, row))
    for key, rows in grouped.items():
        if len(rows) > 1:
            diagnostics.append({'code': 'ambiguous_source_identity',
                                'source_row_indexes': [i for i, _ in rows]})
    checked_rows = 0
    matched_rows = 0
    for i, output in enumerate(output_rows):
        start = len(diagnostics)
        if not isinstance(output, Mapping):
            diagnostics.append({'code': 'output_row_not_mapping', 'output_row_index': i})
            continue
        key = _identity(output.get(output_source_id_field))
        if key is None:
            diagnostics.append({'code': 'output_source_identity_missing_or_invalid', 'output_row_index': i})
            continue
        source = grouped.get(key)
        if not source:
            diagnostics.append({'code': 'unbound_output_source_identity', 'output_row_index': i})
            continue
        if len(source) != 1:
            diagnostics.append({'code': 'output_source_identity_ambiguous', 'output_row_index': i})
            continue
        source_index, row = source[0]
        checked_rows += 1
        for source_field, output_field in pairs:
            where = {'source_row_index': source_index, 'output_row_index': i,
                     'source_field': source_field, 'output_field': output_field}
            if source_field not in row or _missing(row[source_field]):
                diagnostics.append({'code': 'required_source_value_missing', **where})
            elif output_field not in output or _missing(output[output_field]):
                diagnostics.append({'code': 'required_output_value_missing', **where})
            elif not _scalar(row[source_field]) or not _scalar(output[output_field]):
                diagnostics.append({'code': 'unsupported_note_value_type', **where})
            elif type(row[source_field]) is not type(output[output_field]) or row[source_field] != output[output_field]:
                diagnostics.append({'code': 'source_output_value_mismatch', **where,
                                    'source_value_type': type(row[source_field]).__name__,
                                    'output_value_type': type(output[output_field]).__name__})
        if len(diagnostics) == start:
            matched_rows += 1
    if not output_rows:
        diagnostics.append({'code': 'no_output_rows_to_check'})
    return {'schema_version': 1, 'source_rows': len(source_rows), 'output_rows': len(output_rows),
            'source_id_field': source_id_field, 'output_source_id_field': output_source_id_field,
            'required_field_pairs': [{'source': k, 'output': v} for k, v in pairs],
            'bound_rows_checked': checked_rows, 'exact_rows_matched': matched_rows,
            'diagnostics': diagnostics, 'correspondence_gate_passed': not diagnostics,
            'mutation': 'none', 'release_ready': False,
            'scope': 'Explicit supplied source-to-output field correspondence only; no omitted-row, duplicate-output, cardinality or injective-join coverage, '
                     'source authority, policy, financial correctness, runtime or client acceptance inferred'}
