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
    assert (brahms["piece_id"], brahms["variant"]) == ("brahms_symphony-3-mvt-1-excerpt-4", "score")
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


def test_names_from_real_file_names() -> None:
    def name(path: str) -> tuple[str, str, str, str]:
        parts = tuple(path.split("/"))
        n = org.parse(parts, parts[-1].rsplit(".", 1)[0])
        return n.surname, n.first, org.title_slug(n.title), n.variant

    assert name("K„mpf, Karl/Kämpf, Karl - Legende., Op. 31 C.pdf") == ("kampf", "k", "legende-op-31", "cello")
    assert name("Chopin, Frédéric/Chopin, Frédéric - Cello Sonata, Op.65P.pdf") == ("chopin", "f", "cello-sonata-op-65", "piano")
    assert name("Albinoni, Tomaso/Albinoni, Tomaso - Sonata Op 6 No 3 Piano.pdf")[2:] == ("sonata-op-6-no-3", "piano")
    assert name("Bach, J.S/Bach, J.S - 6 Suites for Solo Cello.pdf")[1:] == ("js", "6-suites-for-solo-cello", "score")
    assert name("Bach, CPE/Bach, CPE - Concerto.pdf")[1] == "cpe"
    assert name("Brahms, Johannes/Brahms, Johannes - 21 Hungarian Dances (Piano), WoO 1no 1-5.pdf")[2] == "21-hungarian-dances-piano-woo-1no-1-5"
    assert name("Compilations/X/Split Files/02 - Bartok Concerto for Orchestra-5.pdf") == ("bartok", "", "concerto-for-orchestra-excerpt-5", "score")
    assert len(name("A, B/A, B - " + "very long title " * 10 + ".pdf")[2]) <= org.MAX_TITLE


def test_composer_families_get_initials(tmp_path: Path) -> None:
    for folder, file in [("Bach, Johann Sebastian", "Bach, Johann Sebastian - Suite.pdf"), ("Bach, CPE", "Bach, CPE - Concerto.pdf"),
                         ("Bach, J.S", "Bach, J.S - Suite.pdf"), ("Popper, David", "Popper, David - Etude.pdf")]:
        (tmp_path / folder).mkdir(exist_ok=True)
        (tmp_path / folder / file).write_bytes(b"%PDF")
    path, _ = org.plan(Library(tmp_path))
    rows = {r["source"].split("/")[0]: (r["piece_id"], r["variant"]) for r in org.read_csv(path)}
    assert {rows["Bach, Johann Sebastian"], rows["Bach, J.S"]} == {("bach-js_suite", "score"), ("bach-js_suite", "score-2")}
    assert rows["Bach, CPE"][0] == "bach-cpe_concerto"
    assert rows["Popper, David"][0] == "popper_etude"


def test_names_with_hyphens_particles_and_full_scores() -> None:
    def name(path: str) -> tuple[str, str, str, str]:
        parts = tuple(path.split("/"))
        n = org.parse(parts, parts[-1].rsplit(".", 1)[0])
        return n.surname, n.first, org.title_slug(n.title), n.variant

    assert name("Duport, Jean-Louis/Duport, Jean-Louis - Nocturne en Duo No. 1 cello.pdf") == ("duport", "jl", "nocturne-en-duo-no-1", "cello")
    assert name("Lasso, di/di Lasso - I know a Young Maiden.pdf")[2] == "i-know-a-young-maiden"
    assert name("Ariosti, Attilio/Ariosti, Attilio - Sonata No.3 (in E minor) P & C.pdf")[2:] == ("sonata-no-3-in-e-minor", "score")


def test_apply_all(tmp_path: Path) -> None:
    messy(tmp_path)
    assert main(["organize", "plan", "--root", str(tmp_path)]) == 0
    assert main(["organize", "apply", "all", "--root", str(tmp_path)]) == 0
    lib = Library(tmp_path)
    assert all(todo == 0 for todo, _ in org.batches(lib).values())
    assert len(json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))["pieces"]) == 3
    assert not (tmp_path / "Siklós, Albert").exists()  # emptied folders are removed
