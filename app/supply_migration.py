"""One-time, data-preserving schema upgrade for "supplies" (packets, medicines, fertilizers, ...) bought on a Bill.

* Adds nullable columns (cheap, safe).
* Makes `plant_id` / `expiry_date` optional on seed_packet_batches and `plant_id` optional on accounting_purchase_order_items.
  SQLite cannot drop NOT NULL, so those tables are rebuilt: a new table with the same data is created, the rows are copied,
  the counts are compared, then the tables are swapped. Nothing is assumed to be empty: every row is copied.
* Before any rebuild a verified backup copy of the database file is written next to it (backups/pre_supply_migration_*.db).
* The rebuild runs in one transaction; if any check fails it is rolled back and startup stops with a clear error.

Safe to run again: it only does work that is still missing."""
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("supply_migration")

ADD_COLUMNS = {
    "purchases": [("duplicate_override_reason", "TEXT DEFAULT ''"), ("duplicate_override_by", "VARCHAR(80) DEFAULT ''")],
    "seed_packet_batches": [("item_kind", "VARCHAR(20) NOT NULL DEFAULT 'seed_packet'"), ("item_name", "VARCHAR(200) DEFAULT ''"), ("quantity_unit", "VARCHAR(12) DEFAULT 'packets'")],
    "seed_packet_movements": [("purchase_id", "INTEGER"), ("purchase_line_id", "INTEGER")],
    "accounting_customer_receipts": [("sales_order_id", "INTEGER")],
    "accounting_purchase_orders": [("supplier_bill_number", "VARCHAR(80) DEFAULT ''")],
    "accounting_purchase_order_items": [
        ("item_kind", "VARCHAR(20) NOT NULL DEFAULT 'plant'"), ("lot_number", "VARCHAR(80) DEFAULT ''"), ("company", "VARCHAR(150) DEFAULT ''"),
        ("unit", "VARCHAR(12) DEFAULT ''"), ("mfg_date", "DATE"), ("expiry_date", "DATE"), ("packet_size", "FLOAT"), ("packet_unit", "VARCHAR(10) DEFAULT ''"),
        ("storage_location", "VARCHAR(120) DEFAULT ''"), ("line_notes", "TEXT DEFAULT ''"),
    ],
}
# plant_id: a packet can be "Unassigned / General", medicines have no plant. expiry_date: fertilizers and supplies often have none.
MAKE_NULLABLE = {"seed_packet_batches": ["plant_id", "expiry_date"], "accounting_purchase_order_items": ["plant_id"]}


def _tables(con):
    return {r[0] for r in con.execute("select name from sqlite_master where type='table'")}


def _columns(con, table):
    return {r[1]: r for r in con.execute(f'pragma table_info("{table}")')}


def _backup(con, db_path: Path) -> Path:
    folder = db_path.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"pre_supply_migration_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.db"
    dest = sqlite3.connect(target)
    try:
        con.backup(dest)
    finally:
        dest.close()
    check = sqlite3.connect(target)
    try:
        ok = check.execute("pragma integrity_check").fetchone()[0]
    finally:
        check.close()
    if ok != "ok":
        raise RuntimeError(f"The backup copy {target} failed its integrity check: {ok}")
    return target


def _rebuild_nullable(con, table: str, columns: list) -> None:
    before = con.execute(f'select count(*) from "{table}"').fetchone()[0]
    ddl = con.execute("select sql from sqlite_master where type='table' and name=?", (table,)).fetchone()[0]
    new_ddl = ddl
    for column in columns:
        pattern = r'(["`]?\b' + column + r'\b["`]?\s+[A-Za-z]+(?:\(\d+\))?)\s+NOT\s+NULL'
        new_ddl, n = re.subn(pattern, r"\1", new_ddl, count=1, flags=re.I)
        if n != 1:
            raise RuntimeError(f"Could not find the NOT NULL definition of {table}.{column} to relax")
    new_ddl = re.sub(r'^\s*CREATE\s+TABLE\s+["`]?' + table + r'["`]?', f'CREATE TABLE "{table}__new"', new_ddl, count=1, flags=re.I)
    indexes = [r[0] for r in con.execute("select sql from sqlite_master where type='index' and tbl_name=? and sql is not null", (table,))]
    cols = [r[1] for r in con.execute(f'pragma table_info("{table}")')]
    col_list = ", ".join(f'"{c}"' for c in cols)
    con.execute(f'drop table if exists "{table}__new"')
    con.execute(new_ddl)
    con.execute(f'insert into "{table}__new" ({col_list}) select {col_list} from "{table}"')
    copied = con.execute(f'select count(*) from "{table}__new"').fetchone()[0]
    if copied != before:
        raise RuntimeError(f"{table}: copied {copied} rows but there were {before}")
    con.execute(f'drop table "{table}"')
    con.execute(f'alter table "{table}__new" rename to "{table}"')
    for sql in indexes:
        con.execute(sql)
    after = con.execute(f'select count(*) from "{table}"').fetchone()[0]
    if after != before:
        raise RuntimeError(f"{table}: {after} rows after the rebuild but {before} before")
    logger.info("supply migration: %s.%s are now optional (%s rows kept)", table, ", ".join(columns), after)


def run(engine) -> None:
    url = engine.url
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return
    db_path = Path(url.database)
    if not db_path.exists():
        return
    con = sqlite3.connect(db_path, timeout=60, isolation_level=None)
    try:
        existing = _tables(con)

        def pending():
            out = []
            for t, cols in MAKE_NULLABLE.items():
                if t in existing:
                    have = _columns(con, t)
                    todo = [c for c in cols if have.get(c) and have[c][3] == 1]
                    if todo:
                        out.append((t, todo))
            return out

        # The backup is taken first, outside any transaction (SQLite cannot copy a database that its own connection has open for writing).
        if pending():
            backup = _backup(con, db_path)
            logger.warning("supply migration: backup written to %s", backup)
        con.execute("pragma foreign_keys=OFF")
        con.execute("begin immediate")
        try:
            rebuild = pending()  # checked again now that we hold the write lock
            for table, cols in ADD_COLUMNS.items():
                if table not in existing:
                    continue
                have = _columns(con, table)
                for name, ddl in cols:
                    if name not in have:
                        con.execute(f'alter table "{table}" add column "{name}" {ddl}')
            for table, columns in rebuild:
                _rebuild_nullable(con, table, columns)
            fk_errors = con.execute("pragma foreign_key_check").fetchall()
            con.execute("commit")
            if fk_errors:
                logger.warning("supply migration: foreign key check reported %s existing issue(s) (not caused by this migration)", len(fk_errors))
        except Exception:
            con.execute("rollback")
            raise
    finally:
        con.close()
