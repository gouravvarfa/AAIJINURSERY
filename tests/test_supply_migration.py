"""The supply schema upgrade keeps every row, writes a verified backup first, is safe to run twice, and rolls back on a problem."""
import sqlite3

import pytest
from sqlalchemy import create_engine

from app import supply_migration

OLD_BATCH = """CREATE TABLE seed_packet_batches (
    id INTEGER NOT NULL, record_no VARCHAR(20), plant_id INTEGER NOT NULL, variety VARCHAR(150), company VARCHAR(150), supplier VARCHAR(150),
    batch_number VARCHAR(80) NOT NULL, packet_size FLOAT, packet_unit VARCHAR(10), purchase_date DATE NOT NULL, manufacturing_date DATE,
    expiry_date DATE NOT NULL, storage_location VARCHAR(120), notes TEXT, attachment_url VARCHAR(300), request_id VARCHAR(60) NOT NULL,
    created_by VARCHAR(80), created_at DATETIME, PRIMARY KEY (id), CONSTRAINT uq_seed_packet_batch_request UNIQUE (request_id))"""
OLD_MOVE = """CREATE TABLE seed_packet_movements (
    id INTEGER NOT NULL, batch_id INTEGER NOT NULL, movement_type VARCHAR(20) NOT NULL, quantity INTEGER NOT NULL, reason TEXT, detail TEXT,
    is_exception BOOLEAN NOT NULL, unit_price FLOAT, total_amount FLOAT, invoice_number VARCHAR(80), supplier VARCHAR(150), expense_id INTEGER,
    request_id VARCHAR(60), performed_by VARCHAR(80), created_at DATETIME, PRIMARY KEY (id), FOREIGN KEY(batch_id) REFERENCES seed_packet_batches (id))"""
OLD_POI = """CREATE TABLE accounting_purchase_order_items (
    id INTEGER NOT NULL, purchase_order_id INTEGER NOT NULL, plant_id INTEGER NOT NULL, description VARCHAR(200), quantity INTEGER, unit_price FLOAT,
    tax_rate_id INTEGER, tax_amount FLOAT, line_total FLOAT, variant_id INTEGER, tray_size INTEGER, PRIMARY KEY (id))"""
OLD_PURCHASES = "CREATE TABLE purchases (id INTEGER NOT NULL, supplier VARCHAR(150), PRIMARY KEY (id))"


def _old_db(path, rows=3):
    con = sqlite3.connect(path)
    for ddl in (OLD_BATCH, OLD_MOVE, OLD_POI, OLD_PURCHASES):
        con.execute(ddl)
    con.execute("CREATE INDEX ix_seed_packet_batches_plant_id ON seed_packet_batches (plant_id)")
    con.execute("CREATE INDEX ix_seed_packet_batches_expiry_date ON seed_packet_batches (expiry_date)")
    for i in range(1, rows + 1):
        con.execute("insert into seed_packet_batches (id, record_no, plant_id, variety, company, batch_number, purchase_date, expiry_date, request_id) values (?,?,?,?,?,?,?,?,?)",
                    (i, f"SP-{i}", 10 + i, "V", "Co", f"LOT-{i}", "2026-10-01", "2027-10-01", f"req-{i}"))
        con.execute("insert into seed_packet_movements (batch_id, movement_type, quantity, is_exception, request_id) values (?,?,?,?,?)", (i, "RECEIPT", 5 * i, 0, f"m-{i}"))
        con.execute("insert into accounting_purchase_order_items (purchase_order_id, plant_id, description, quantity, unit_price) values (?,?,?,?,?)", (1, 10 + i, f"plant {i}", i, 2.5))
    con.execute("insert into purchases (id, supplier) values (1, 'S')")
    con.commit()
    con.close()


def _counts(path):
    con = sqlite3.connect(path)
    try:
        return {t: con.execute(f"select count(*) from {t}").fetchone()[0] for t in ("seed_packet_batches", "seed_packet_movements", "accounting_purchase_order_items", "purchases")}
    finally:
        con.close()


def test_every_row_is_kept_columns_become_optional_and_a_backup_is_written(tmp_path):
    db = tmp_path / "old.db"
    _old_db(db, rows=4)
    before = _counts(db)
    supply_migration.run(create_engine(f"sqlite:///{db}"))
    assert _counts(db) == before
    con = sqlite3.connect(db)
    notnull = lambda t, c: [r[3] for r in con.execute(f"pragma table_info({t})") if r[1] == c][0]
    assert notnull("seed_packet_batches", "plant_id") == 0 and notnull("seed_packet_batches", "expiry_date") == 0 and notnull("accounting_purchase_order_items", "plant_id") == 0
    assert notnull("seed_packet_batches", "batch_number") == 1  # everything else stays as strict as before
    assert con.execute("select plant_id, expiry_date, item_kind, quantity_unit from seed_packet_batches where id=2").fetchone() == (12, "2027-10-01", "seed_packet", "packets")
    assert con.execute("select item_kind, quantity from accounting_purchase_order_items where id=1").fetchone() == ("plant", 1)  # old lines become kind "plant"
    names = {r[0] for r in con.execute("select name from sqlite_master where type='index'")}
    assert {"ix_seed_packet_batches_plant_id", "ix_seed_packet_batches_expiry_date"} <= names
    # a NULL plant / expiry is now allowed
    con.execute("insert into seed_packet_batches (record_no, plant_id, batch_number, purchase_date, expiry_date, request_id) values ('SP-9', NULL, 'X', '2026-10-01', NULL, 'new-1')")
    assert con.execute("pragma integrity_check").fetchone()[0] == "ok"
    con.close()
    backups = list((tmp_path / "backups").glob("pre_supply_migration_*.db"))
    assert len(backups) == 1
    bk = sqlite3.connect(backups[0])
    try:
        assert bk.execute("select count(*) from seed_packet_batches").fetchone()[0] == 4  # the backup is the data as it was before
        assert [r[3] for r in bk.execute("pragma table_info(seed_packet_batches)") if r[1] == "plant_id"] == [1]
        assert bk.execute("pragma integrity_check").fetchone()[0] == "ok"
    finally:
        bk.close()


def test_running_it_again_changes_nothing_and_makes_no_second_backup(tmp_path):
    db = tmp_path / "old.db"
    _old_db(db)
    eng = create_engine(f"sqlite:///{db}")
    supply_migration.run(eng)
    snapshot = sqlite3.connect(db).execute("select sql from sqlite_master where name='seed_packet_batches'").fetchone()[0]
    supply_migration.run(eng)
    assert sqlite3.connect(db).execute("select sql from sqlite_master where name='seed_packet_batches'").fetchone()[0] == snapshot
    assert len(list((tmp_path / "backups").glob("*.db"))) == 1


def test_a_table_with_lots_of_rows_is_copied_completely(tmp_path):
    db = tmp_path / "old.db"
    _old_db(db, rows=250)
    supply_migration.run(create_engine(f"sqlite:///{db}"))
    assert _counts(db)["seed_packet_batches"] == 250 and _counts(db)["accounting_purchase_order_items"] == 250


def test_a_failed_rebuild_rolls_back_and_leaves_the_old_tables_untouched(tmp_path, monkeypatch):
    db = tmp_path / "old.db"
    _old_db(db)
    before = _counts(db)

    def boom(con, table, columns):
        con.execute(f'create table "{table}__half" (x integer)')
        raise RuntimeError("simulated failure half way")

    monkeypatch.setattr(supply_migration, "_rebuild_nullable", boom)
    with pytest.raises(RuntimeError):
        supply_migration.run(create_engine(f"sqlite:///{db}"))
    con = sqlite3.connect(db)
    assert _counts(db) == before
    assert [r[3] for r in con.execute("pragma table_info(seed_packet_batches)") if r[1] == "plant_id"] == [1]  # still the old, intact table
    assert not con.execute("select 1 from sqlite_master where name like '%__half'").fetchone()  # nothing half-done left behind
    assert "item_kind" not in [r[1] for r in con.execute("pragma table_info(seed_packet_batches)")]  # the added columns rolled back too
    con.close()
    monkeypatch.undo()
    supply_migration.run(create_engine(f"sqlite:///{db}"))  # and a later run succeeds
    assert _counts(db) == before


def test_a_fresh_database_needs_no_rebuild_and_no_backup(tmp_path):
    db = tmp_path / "fresh.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE seed_packet_batches (id INTEGER NOT NULL, plant_id INTEGER, expiry_date DATE, PRIMARY KEY (id))")
    con.commit()
    con.close()
    supply_migration.run(create_engine(f"sqlite:///{db}"))
    assert not (tmp_path / "backups").exists()
