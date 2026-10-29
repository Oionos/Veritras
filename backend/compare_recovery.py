"""Read-only comparison of explicit frozen PostgreSQL recovery targets.

No application imports, migrations, provider mutations, or restore operations.
URLs come only from SOURCE_DATABASE_URL / TARGET_DATABASE_URL, never CLI args.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from constraint_fingerprint import NORMALIZATION, canonical_constraint

SYSTEM_SCHEMA = (
    "n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\' AND n.nspname <> 'information_schema'"
)
CATALOGS = {
    "database_properties": """SELECT pg_encoding_to_char(d.encoding),d.datcollate,d.datctype,
        to_jsonb(d)->>'datlocprovider',coalesce(to_jsonb(d)->>'datlocale',to_jsonb(d)->>'daticulocale')
        FROM pg_database d WHERE d.datname=current_database()""",
    "schemas": f"SELECT n.nspname FROM pg_namespace n WHERE {SYSTEM_SCHEMA} ORDER BY 1",
    "relations": f"""SELECT n.nspname, c.relname, c.relkind, c.relrowsecurity, c.relforcerowsecurity,
        c.relpersistence, c.relreplident, c.reloptions,
        CASE WHEN c.relkind='p' THEN pg_get_partkeydef(c.oid) END AS partition_key,
        pg_get_expr(c.relpartbound,c.oid) AS partition_bound
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE {SYSTEM_SCHEMA} AND c.relkind IN ('r','p','v','m','f') ORDER BY 1,2""",
    "columns": f"""SELECT n.nspname,c.relname,a.attnum,a.attname,format_type(a.atttypid,a.atttypmod),
        a.attnotnull,a.attidentity,a.attgenerated,pg_get_expr(d.adbin,d.adrelid) AS default_expression,
        co.collname AS collation
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
        LEFT JOIN pg_collation co ON co.oid=a.attcollation
        WHERE {SYSTEM_SCHEMA} AND c.relkind IN ('r','p','v','m','f') AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY 1,2,3""",
    "constraints": f"""SELECT n.nspname,c.relname,k.conname,pg_get_constraintdef(k.oid,true),k.convalidated
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {SYSTEM_SCHEMA} ORDER BY 1,2,3""",
    "indexes": f"""SELECT n.nspname,c.relname,i.relname,pg_get_indexdef(x.indexrelid),x.indisvalid,x.indisready
        FROM pg_index x JOIN pg_class c ON c.oid=x.indrelid JOIN pg_class i ON i.oid=x.indexrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {SYSTEM_SCHEMA} ORDER BY 1,2,3""",
    "triggers": f"""SELECT n.nspname,c.relname,t.tgname,pg_get_triggerdef(t.oid,true),t.tgenabled
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {SYSTEM_SCHEMA} AND NOT t.tgisinternal ORDER BY 1,2,3""",
    "rules": f"""SELECT n.nspname,c.relname,r.rulename,pg_get_ruledef(r.oid,true)
        FROM pg_rewrite r JOIN pg_class c ON c.oid=r.ev_class
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {SYSTEM_SCHEMA} ORDER BY 1,2,3""",
    "functions": f"""SELECT n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),pg_get_functiondef(p.oid)
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE {SYSTEM_SCHEMA} AND p.prokind IN ('f','p') ORDER BY 1,2,3""",
    "enums": f"""SELECT n.nspname,t.typname,e.enumsortorder,e.enumlabel FROM pg_enum e
        JOIN pg_type t ON t.oid=e.enumtypid JOIN pg_namespace n ON n.oid=t.typnamespace
        WHERE {SYSTEM_SCHEMA} ORDER BY 1,2,3""",
    "domains": f"""SELECT n.nspname,t.typname,format_type(t.typbasetype,t.typtypmod),t.typnotnull,t.typdefault,
        (SELECT array_agg(pg_get_constraintdef(c.oid,true) ORDER BY c.conname)
         FROM pg_constraint c WHERE c.contypid=t.oid) AS checks
        FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
        WHERE {SYSTEM_SCHEMA} AND t.typtype='d' ORDER BY 1,2""",
    "policies": f"""SELECT n.nspname,c.relname,p.polname,p.polcmd,p.polpermissive,
        (SELECT array_agg(CASE WHEN role_id=0 THEN 'PUBLIC' ELSE pg_get_userbyid(role_id) END ORDER BY role_id)
         FROM unnest(p.polroles) AS role_id) AS roles,
        pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid)
        FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {SYSTEM_SCHEMA} ORDER BY 1,2,3""",
    "extensions": """SELECT e.extname,e.extversion,n.nspname FROM pg_extension e
        JOIN pg_namespace n ON n.oid=e.extnamespace ORDER BY 1""",
    "sequence_definitions": f"""SELECT n.nspname,c.relname,format_type(s.seqtypid,NULL),s.seqstart,s.seqincrement,
        s.seqmax,s.seqmin,s.seqcache,s.seqcycle FROM pg_sequence s JOIN pg_class c ON c.oid=s.seqrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {SYSTEM_SCHEMA} ORDER BY 1,2""",
    "sequence_ownership": f"""SELECT n.nspname,s.relname,tn.nspname,t.relname,a.attname,d.deptype
        FROM pg_class s JOIN pg_namespace n ON n.oid=s.relnamespace
        JOIN pg_depend d ON d.classid='pg_class'::regclass AND d.objid=s.oid
        AND d.refclassid='pg_class'::regclass AND d.deptype IN ('a','i')
        JOIN pg_class t ON t.oid=d.refobjid JOIN pg_namespace tn ON tn.oid=t.relnamespace
        JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=d.refobjsubid
        WHERE {SYSTEM_SCHEMA} AND s.relkind='S' ORDER BY 1,2,3,4,5""",
    "inheritance": f"""SELECT n.nspname,c.relname,pn.nspname,p.relname,i.inhseqno FROM pg_inherits i
        JOIN pg_class c ON c.oid=i.inhrelid JOIN pg_class p ON p.oid=i.inhparent
        JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_namespace pn ON pn.oid=p.relnamespace
        WHERE {SYSTEM_SCHEMA} ORDER BY 1,2,3,4,5""",
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def checked_url(value, expected):
    """Validate before opening a socket; URL query parameters cannot override identity."""
    url = make_url(value)
    if (
        set(expected) != {"host", "port", "database"}
        or type(expected["port"]) is not int
        or not 1 <= expected["port"] <= 65535
        or url.drivername not in {"postgresql", "postgres", "postgresql+psycopg2"}
        or not url.host
        or not url.database
        or not url.username
        or not re.fullmatch(r"[a-zA-Z0-9.:-]+", url.host)
        or (url.host.lower(), url.port or 5432, url.database)
        != (expected["host"].lower(), expected["port"], expected["database"])
        or "-pooler." in url.host
        or set(url.query)
        - {"sslmode", "sslrootcert", "channel_binding", "connect_timeout"}
    ):
        raise ValueError("Invalid recovery target")
    if (
        url.host not in {"localhost", "127.0.0.1", "::1"}
        and url.query.get("sslmode") != "verify-full"
    ):
        raise ValueError("Verified TLS required for hosted recovery targets")
    # Bound connection establishment independently of the SQL statement timeout.
    return url.set(drivername="postgresql+psycopg2").update_query_dict(
        {"connect_timeout": "10"}
    )


def validate_targets(manifest, source_url, target_url):
    if (
        set(manifest) != {"version", "frozen", "source", "target"}
        or type(manifest["version"]) is not int
        or manifest["version"] != 1
        or manifest["frozen"] is not True
    ):
        raise ValueError("Reviewed frozen-target manifest required")
    source = checked_url(source_url, manifest["source"])
    target = checked_url(target_url, manifest["target"])
    if (source.host.lower(), source.port or 5432, source.database) == (
        target.host.lower(),
        target.port or 5432,
        target.database,
    ):
        raise ValueError("Distinct recovery targets required")
    return source, target


def rows(connection, sql):
    return [list(row) for row in connection.execute(text(sql))]


def fingerprint(engine, *, expected_database, stable_cursor=False):
    """One consistent, bounded, read-only snapshot; emit hashes and counts only."""
    if engine.dialect.name != "postgresql":
        raise ValueError("PostgreSQL recovery comparison required")
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            # Never silently fingerprint an RLS-filtered subset of the backup.
            # A role lacking complete access must fail rather than compare empty rows.
            connection.execute(text("SET LOCAL row_security = off"))
            connection.execute(text("SET LOCAL statement_timeout = '60s'"))
            connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            connection.execute(
                text("SET LOCAL idle_in_transaction_session_timeout = '120s'")
            )
            connection.execute(text("SET LOCAL timezone = 'UTC'"))
            connection.execute(text("SET LOCAL datestyle = 'ISO, YMD'"))
            connection.execute(text("SET LOCAL extra_float_digits = 3"))
            connection.execute(text("SET LOCAL standard_conforming_strings = on"))
            connection.execute(text("SET LOCAL search_path = pg_catalog"))
            database, read_only = connection.execute(
                text(
                    "SELECT current_database(), current_setting('transaction_read_only')"
                )
            ).one()
            if database != expected_database or read_only != "on":
                raise ValueError("Unexpected recovery connection")
            catalogs = {name: rows(connection, sql) for name, sql in CATALOGS.items()}
            for constraint in catalogs["constraints"]:
                constraint[3] = canonical_constraint(constraint[3])
            relations = catalogs["relations"]
            if not relations or any(row[2] == "f" for row in relations):
                raise ValueError("Empty or externally backed recovery schema")
            quote = engine.dialect.identifier_preparer.quote
            data = {}
            access = {}
            for schema, table, kind, *_ in relations:
                identity = f"{schema}.{table}"
                qualified = f"{quote(schema)}.{quote(table)}"
                access[identity] = list(
                    connection.execute(
                        text(
                            "SELECT has_table_privilege(:relation,'SELECT'),has_table_privilege(:relation,'INSERT'),"
                            "has_table_privilege(:relation,'UPDATE'),has_table_privilege(:relation,'DELETE')"
                        ),
                        {"relation": qualified},
                    ).one()
                )
                if kind not in {"r", "p", "m"}:
                    continue
                # PostgreSQL performs the deterministic sort (and can spill to
                # its private temp storage). Client memory stays bounded.
                payload = "to_jsonb(t)"
                if stable_cursor and identity == "public.indexer_cursors":
                    payload = "(to_jsonb(t) - 'updated_at')"
                result = connection.execution_options(
                    stream_results=True, max_row_buffer=1000
                ).execute(
                    text(
                        f'SELECT {payload}::text FROM {qualified} AS t ORDER BY {payload}::text COLLATE "C"'
                    )
                )
                content, count = hashlib.sha256(), 0
                for (value,) in result:
                    encoded = value.encode()
                    content.update(len(encoded).to_bytes(8, "big"))
                    content.update(encoded)
                    count += 1
                result.close()
                # Reset server-cursor mode for catalog and session commands.
                connection.execution_options(stream_results=False)
                data[identity] = {"count": count, "digest": content.hexdigest()}
            sequences = {}
            for schema, name, *_ in catalogs["sequence_definitions"]:
                value = connection.execute(
                    text(
                        f"SELECT last_value,is_called FROM {quote(schema)}.{quote(name)}"
                    )
                ).one()
                sequences[f"{schema}.{name}"] = digest(list(value))
            return {
                "tables": data,
                "schema": {name: digest(value) for name, value in catalogs.items()},
                "sequence_state": sequences,
                "effective_table_access": digest(access),
                "read_only": True,
                "normalization": (
                    "cursor_poll_timestamp_excluded"
                    if stable_cursor
                    else "complete_rows"
                ),
                "constraint_normalization": NORMALIZATION,
            }


def compare(source, target):
    differences = []
    if source.get("normalization") != target.get("normalization"):
        differences.append({"section": "normalization"})
    if source.get("constraint_normalization") != target.get("constraint_normalization"):
        differences.append({"section": "constraint_normalization"})
    for section in ("tables", "schema", "sequence_state"):
        for name in sorted(set(source[section]) | set(target[section])):
            if source[section].get(name) != target[section].get(name):
                differences.append({"section": section, "object": name})
    if source["effective_table_access"] != target["effective_table_access"]:
        differences.append({"section": "effective_table_access"})
    return {"matches": not differences, "differences": differences}


def summarize_differences(comparison):
    """Public diagnostic categories only; object names and snapshots stay private."""
    differences = comparison.get("differences")
    if not isinstance(differences, list):
        return {"available": False}
    sections = {}
    catalogs = set()
    allowed = {"tables", "schema", "sequence_state", "effective_table_access", "normalization", "constraint_normalization"}
    unclassified = 0
    for difference in differences:
        if not isinstance(difference, dict):
            unclassified += 1
            continue
        section = difference.get("section")
        if not isinstance(section, str) or section not in allowed:
            unclassified += 1
            continue
        sections[section] = sections.get(section, 0) + 1
        if section == "schema":
            name = difference.get("object")
            if isinstance(name, str) and name in CATALOGS:
                catalogs.add(name)
            else:
                unclassified += 1
    return {
        "available": True,
        "difference_count": len(differences),
        "sections": sections,
        "schema_categories": sorted(catalogs),
        "unclassified_count": unclassified,
    }


def run_comparison(manifest, source_url, target_url):
    urls = validate_targets(manifest, source_url, target_url)
    snapshots = []
    for url in urls:
        engine = create_engine(url, poolclass=NullPool, hide_parameters=True)
        try:
            snapshots.append(fingerprint(engine, expected_database=url.database))
        finally:
            engine.dispose()
    return {
        "report_version": 1,
        "report_type": "read_only_recovery_comparison",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "manifest_digest": digest(manifest),
        "source": snapshots[0],
        "target": snapshots[1],
        **compare(*snapshots),
        "limitations": [
            "Caller must freeze targets and verify provider branch ownership before this read-only comparison",
            "Object owners and raw role grants excluded; effective table access compares the supplied roles",
            "Does not prove off-provider backup retention, RPO/RTO, application reads or replay",
        ],
        "authorizes_activation": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_comparison(
            json.loads(args.manifest.read_text()),
            os.environ["SOURCE_DATABASE_URL"],
            os.environ["TARGET_DATABASE_URL"],
        )
    except Exception:
        report = {
            "report_version": 1,
            "matches": False,
            "state": "comparison_failed",
            "authorizes_activation": False,
        }
    # Never overwrite a previous report, and keep new reports private by default.
    try:
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(report, output, sort_keys=True, indent=2)
            output.write("\n")
    except OSError:
        print(json.dumps({"matches": False, "state": "report_write_failed"}))
        return 2
    print(
        json.dumps(
            {
                "matches": report["matches"],
                "state": "compared" if "source" in report else "comparison_failed",
            }
        )
    )
    return 0 if report["matches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
