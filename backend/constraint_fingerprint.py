"""Conservative canonical form for PostgreSQL's literal varchar-array rewrite.

pg_dump reparsing can distribute a text[] cast over varchar literal elements.
Only this lossless builtin cast is normalized. Other SQL remains unchanged; all
surrounding syntax, literal values, type modifiers and constraint flags survive.
No SQL is executed while parsing or normalizing a definition.
Input is pg_get_constraintdef output under search_path=pg_catalog, so bare
builtin type names cannot resolve to a user-defined type.
"""

import pglast
from pglast import parse_sql

NORMALIZATION = "literal_varchar_text_arrays_v1:" + pglast.__version__
POSITIONS = {
    "location", "stmt_location", "stmt_len", "list_start", "list_end",
    "rexpr_list_start", "rexpr_list_end",
}


def builtin_type(node, name, *, array=False):
    if not isinstance(node, dict) or node.get("@") != "TypeName":
        return False
    names = [value.get("sval") for value in node.get("names") or []]
    bounds = [{"@": "Integer", "ival": -1}] if array else None
    return (
        names in ([name], ["pg_catalog", name])
        and node.get("typmods") is None and node.get("typemod") == -1
        and node.get("arrayBounds") == bounds
        and not node.get("setof") and not node.get("pct_type")
    )


def varchar_literal(node):
    if not isinstance(node, dict) or node.get("@") != "TypeCast":
        return False
    value = node.get("arg", {})
    return (
        builtin_type(node.get("typeName"), "varchar")
        and value.get("@") == "A_Const"
        and not value.get("isnull")
        and value.get("val", {}).get("@") == "String"
    )


def without_positions(value):
    if isinstance(value, dict):
        return {key: without_positions(item) for key, item in value.items() if key not in POSITIONS}
    if isinstance(value, (list, tuple)):
        return [without_positions(item) for item in value]
    return value


def canonical_constraint(definition):
    if not isinstance(definition, str) or not definition.startswith("CHECK (") or len(definition) > 65536:
        return definition
    try:
        statements = parse_sql(
            "ALTER TABLE recovery_relation ADD CONSTRAINT recovery_constraint " + definition
        )
        if len(statements) != 1:
            return definition
        statement = statements[0]()["stmt"]
        if statement.get("@") != "AlterTableStmt" or len(statement.get("cmds") or []) != 1:
            return definition
        constraint = statement["cmds"][0]["def_"]
        if constraint.get("contype", {}).get("name") != "CONSTR_CHECK":
            return definition
        matched = False

        def visit(value):
            nonlocal matched
            if isinstance(value, (list, tuple)):
                return [visit(item) for item in value]
            if not isinstance(value, dict):
                return value
            value = {key: visit(item) for key, item in value.items()}
            if value.get("@") == "TypeCast" and builtin_type(
                value.get("typeName"), "text", array=True
            ):
                array = value.get("arg", {})
                elements = array.get("elements") or []
                if array.get("@") == "A_ArrayExpr" and elements and all(map(varchar_literal, elements)):
                    scalar = {**value["typeName"], "arrayBounds": None}
                    matched = True
                    return {
                        **array,
                        "elements": [
                            {"@": "TypeCast", "arg": item, "typeName": scalar}
                            for item in elements
                        ],
                    }
            if value.get("@") == "A_ArrayExpr":
                elements = value.get("elements") or []
                if elements and all(
                    item.get("@") == "TypeCast"
                    and builtin_type(item.get("typeName"), "text")
                    and varchar_literal(item.get("arg"))
                    for item in elements
                ):
                    matched = True
            return value

        normalized = visit(constraint)
        if matched:
            return {"normalization": NORMALIZATION, "constraint": without_positions(normalized)}
    except Exception:
        # Unsupported syntax stays subject to the original exact comparison.
        return definition
    return definition
