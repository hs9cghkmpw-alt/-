"""Isolated sqlite-vec compatibility probe; not imported by Brain Twin runtime."""
from __future__ import annotations

import importlib.metadata
import platform
import sqlite3
import struct
import sys
from pathlib import Path

import sqlite_vec


def _create_index(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE VIRTUAL TABLE memory_vector_index USING vec0("
        "memory_id TEXT PRIMARY KEY, embedding FLOAT[3] distance_metric=cosine)"
    )


def main() -> None:
    db_path = Path(__file__).with_name("sqlite_vec_spike.sqlite3")
    db_path.unlink(missing_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        extension_path = Path(sqlite_vec.loadable_path()).resolve()
        package_dir = Path(sqlite_vec.__file__).resolve().parent
        if package_dir not in extension_path.parents:
            raise RuntimeError("sqlite-vec extension path is outside the installed package")

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        version = conn.execute("SELECT vec_version()").fetchone()[0]

        _create_index(conn)
        rows = {
            "a": [1.0, 0.0, 0.0],
            "b": [0.8, 0.2, 0.0],
            "c": [0.0, 1.0, 0.0],
        }
        conn.executemany(
            "INSERT INTO memory_vector_index(memory_id, embedding) VALUES (?, ?)",
            [(key, sqlite_vec.serialize_float32(vector)) for key, vector in rows.items()],
        )
        knn = conn.execute(
            "SELECT memory_id, distance FROM memory_vector_index "
            "WHERE embedding MATCH ? AND k = 3 ORDER BY distance",
            (sqlite_vec.serialize_float32([1.0, 0.0, 0.0]),),
        ).fetchall()
        assert [row[0] for row in knn] == ["a", "b", "c"]
        assert abs(knn[0][1]) < 1e-6

        # vec0 does not support UPDATE in 0.1.9; delete+insert is the upsert primitive.
        conn.execute("DELETE FROM memory_vector_index WHERE memory_id = 'b'")
        conn.execute(
            "INSERT INTO memory_vector_index(memory_id, embedding) VALUES (?, ?)",
            ("b", sqlite_vec.serialize_float32([-1.0, 0.0, 0.0])),
        )
        conn.execute("DELETE FROM memory_vector_index WHERE memory_id = 'c'")
        assert conn.execute("SELECT count(*) FROM memory_vector_index").fetchone()[0] == 2

        conn.execute("DROP TABLE memory_vector_index")
        _create_index(conn)
        conn.execute(
            "INSERT INTO memory_vector_index(memory_id, embedding) VALUES (?, ?)",
            ("rebuilt", sqlite_vec.serialize_float32([1.0, 0.0, 0.0])),
        )
        assert conn.execute("SELECT count(*) FROM memory_vector_index").fetchone()[0] == 1
        conn.commit()

        print(f"python={sys.version.split()[0]}")
        print(f"sqlite={sqlite3.sqlite_version}")
        print(f"sqlite_vec_package={importlib.metadata.version('sqlite-vec')}")
        print(f"sqlite_vec_runtime={version}")
        print(f"windows={platform.platform()}")
        print(f"architecture={platform.machine()} {struct.calcsize('P') * 8}-bit")
        print(f"extension_path={extension_path}")
        print(f"knn={knn}")
        print("result=PASS")
    finally:
        conn.close()
        db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
