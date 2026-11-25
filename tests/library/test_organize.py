from __future__ import annotations

import json
from pathlib import Path

from lento_library import organize as org
from lento_library.cli import main
from lento_library.library import Library


def messy(root: Path) -> None:
    (root / "Villa-Lobos, Heitor").mkdir()
    (root / "Villa-Lobos, Heitor" / "Aria (Bachianas 5).pdf").write_bytes(b"%PDF /Type /Page")
    (root / "Villa-Lobos, Heitor" / "Aria (Bachianas 5).musicxml").write_text("<score-partwise/>")
    (root / "Villa-Lobos, Heitor" / "Aria (Bachianas 5).quality.json").write_text('{"level": "OK"}')
    (root / "Siklós, Albert").mkdir()
    (root / "Siklós, Albert" / "Etude.pdf").write_bytes(b"%PDF")
    (root / "Excerpts" / "Brahms").mkdir(parents=True)
    (root / "Excerpts" / "Brahms" / "36 - Brahms Symphony 3 mvt 1-4.musicxml").write_text("<score-partwise/>")
    (root / "notes.txt").write_text("not a score")


def test_plan_names_files_and_moves_nothing(tmp_path: Path) -> None:
    messy(tmp_path)
    path, n = org.plan(Library(tmp_path))
    rows = {r["source"]: r for r in org.read_csv(path)}
    assert n == 4
    aria = rows["Villa-Lobos, Heitor/Aria (Bachianas 5).pdf"]
    assert (aria["piece_id"], aria["variant"], aria["batch"]) == ("villa-lobos_aria-bachianas-5", "score", "Villa-Lobos, Heitor")
    assert rows["Siklós, Albert/Etude.pdf"]["piece_id"] == "siklos_etude"
    brahms = rows["Excerpts/Brahms/36 - Brahms Symphony 3 mvt 1-4.musicxml"]
    assert (brahms["piece_id"], brahms["variant"]) == ("brahms_symphony-3-mvt-1", "part-4")
    assert (tmp_path / "Siklós, Albert" / "Etude.pdf").exists()


def test_plan_keeps_edits_when_run_again(tmp_path: Path) -> None:
    messy(tmp_path)
    lib = Library(tmp_path)
    path, _ = org.plan(lib)
    rows = org.read_csv(path)
    for r in rows:
        if r["source"].endswith("Etude.pdf"):
            r["piece_id"], r["action"] = "siklos_etude-1", "skip"
    org.write_csv(path, org.PLAN_COLUMNS, rows)
    org.plan(lib)
    etude = next(r for r in org.read_csv(path) if r["source"].endswith("Etude.pdf"))
    assert (etude["piece_id"], etude["action"]) == ("siklos_etude-1", "skip")


def test_apply_one_batch_then_undo(tmp_path: Path, capsys) -> None:
    messy(tmp_path)
    lib = Library(tmp_path)
    assert main(["organize", "plan", "--root", str(tmp_path)]) == 0
    assert main(["organize", "apply", "Villa-Lobos, Heitor", "--root", str(tmp_path)]) == 0
    d = tmp_path / "pieces" / "villa-lobos_aria-bachianas-5"
    assert sorted(p.name for p in d.iterdir()) == [
        "villa-lobos_aria-bachianas-5__score.musicxml",
        "villa-lobos_aria-bachianas-5__score.pdf",
        "villa-lobos_aria-bachianas-5__score.quality.json",
    ]
    assert (tmp_path / "Siklós, Albert" / "Etude.pdf").exists()  # other batches stay put
    cat = lib.catalog()
    assert [(r["piece_id"], r["composer"], r["title"]) for r in cat] == [("villa-lobos_aria-bachianas-5", "Villa-Lobos, Heitor", "Aria (Bachianas 5)")]
    index = json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))
    assert [p["id"] for p in index["pieces"]] == ["villa-lobos_aria-bachianas-5"]
    assert org.batches(lib)["Villa-Lobos, Heitor"] == (0, 2)
    assert main(["organize", "apply", "Villa-Lobos, Heitor", "--root", str(tmp_path)]) == 0  # again: nothing to do

    assert main(["organize", "undo", "Villa-Lobos, Heitor", "--root", str(tmp_path)]) == 0
    assert (tmp_path / "Villa-Lobos, Heitor" / "Aria (Bachianas 5).pdf").exists()
    assert (tmp_path / "Villa-Lobos, Heitor" / "Aria (Bachianas 5).quality.json").exists()
    assert not d.exists()
    assert lib.catalog() == []


def test_apply_checks_everything_before_moving(tmp_path: Path) -> None:
    messy(tmp_path)
    lib = Library(tmp_path)
    path, _ = org.plan(lib)
    rows = org.read_csv(path)
    for r in rows:
        if r["source"].endswith(".musicxml") and r["batch"] == "Villa-Lobos, Heitor":
            r["piece_id"] = "Bad Id"
    org.write_csv(path, org.PLAN_COLUMNS, rows)
    moved, problems = org.apply(lib, "Villa-Lobos, Heitor")
    assert moved == [] and len(problems) == 1
    assert (tmp_path / "Villa-Lobos, Heitor" / "Aria (Bachianas 5).pdf").exists()


def test_files_already_in_pieces_are_not_planned(tmp_path: Path) -> None:
    (tmp_path / "pieces" / "bach_x").mkdir(parents=True)
    (tmp_path / "pieces" / "bach_x" / "bach_x__score.pdf").write_bytes(b"%PDF")
    assert org.plan(Library(tmp_path))[1] == 0
