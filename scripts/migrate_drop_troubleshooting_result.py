"""Drop the Anker-era troubleshooting_result column from the live case table.

The column is NOT NULL without a server default, so keeping it while the ORM
no longer supplies a value would break every INSERT. The case table currently
holds no rows, so DROP COLUMN is safe (SQLite 3.35+ implements it natively).
"""

import sqlite3

DB = "data/runtime/anker_agent.sqlite3"

con = sqlite3.connect(DB)
con.execute("PRAGMA foreign_keys=OFF")

before = {row[1] for row in con.execute('PRAGMA table_info("case")')}
print("drops 之前含 troubleshooting_result:", "troubleshooting_result" in before)

if "troubleshooting_result" in before:
    con.execute('ALTER TABLE "case" DROP COLUMN troubleshooting_result')
    con.commit()

after = {row[1] for row in con.execute('PRAGMA table_info("case")')}
print("drops 之后仍含 troubleshooting_result:", "troubleshooting_result" in after)

remaining_anker = sorted(
    name
    for name in after
    if any(key in name for key in ("warrant", "dealer", "troubleshoot"))
)
print("case 表仍保留的安克相关列:", remaining_anker)

rows = con.execute('SELECT count(*) FROM "case"').fetchone()[0]
print("case 行数:", rows)
print("integrity_check:", con.execute("PRAGMA integrity_check").fetchone()[0])
con.close()
