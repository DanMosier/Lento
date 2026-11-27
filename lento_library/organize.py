"""Filing an existing, unorganized score folder into the library layout, one batch at a time.

  plan   scans every score file outside pieces/ and writes organize-plan.csv: for each file, its batch (the top
         folder it is in), the piece_id and variant it would get, and action "move". Nothing is moved. Edit the
         CSV in Excel or Sheets: fix ids, set action to "skip" for anything that should stay where it is.
  apply  moves the files of one batch as the plan says, adds catalog rows for the PDFs, and logs every move to
         organize-log.csv, so that batch can be put back with `undo`.
  undo   moves a batch's files back where they were (from organize-log.csv).

Files that belong together (a PDF, the MusicXML made from it, its quality report) share a stem, so they move
together and keep sharing one.
"""

from __future__ import annotations

import csv
import datetime
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from lento_library.library import (
    COLUMNS,
    ID_RE,
    INDEX_NAME,
    KINDS,
    MUSESCORE,
    REQUESTS,
    VARIANT_RE,
    Library,
)

PLAN = "organize-plan.csv"
LOG = "organize-log.csv"
PLAN_COLUMNS = ["batch", "source", "piece_id", "variant", "action", "composer", "title", "note"]
LOG_COLUMNS = ["batch", "source", "dest", "moved"]
SCORE_EXT = set(KINDS) | set(MUSESCORE)
SKIP_TOP = {"pieces", REQUESTS, "inbox"}


def slug(text: str) -> str:
    text = re.sub(r"['’](?=\w)", "", text)  # "Fiddl'osophy" -> "fiddlosophy"
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


PARTICLES = {"von", "van", "de", "der", "den", "d", "la", "le", "du", "da", "di", "jr", "sr", "zu"}
MAX_TITLE = 60  # keeps pieces/<id>/<id>__<variant>.pdf well inside Windows' 260-character path limit

# Surnames (as slugs) recognised anywhere in a file name that gives no "Last, First - Title". Composers already in
# the library's pieces/ are recognised too.
COMPOSERS = set("""
albeniz albinoni arensky arriaga bach barber bartok beethoven bellini berlioz bernstein bizet bloch boccherini
borodin brahms breval bridge britten bruch casals cassado chopin corelli couperin cui czerny davydov debussy delius
dotzauer dukas duport dvorak einaudi elgar faure franck gabrielli gershwin glass glazunov glinka gluck goltermann
gounod granados grieg grutzmacher handel haydn hindemith holst hummel ibert janacek kabalevsky khachaturian klengel
kodaly kreisler kummer lalo lee liszt mahler marais marcello massenet mendelssohn monteverdi mozart mussorgsky
offenbach paganini pergolesi piatti piazzolla popper poulenc prokofiev puccini purcell rachmaninoff rachmaninov
ravel respighi romberg rossini saint-saens sammartini satie scarlatti schnittke schroeder schubert schumann
servais shostakovich sibelius smetana squire stamitz strauss stravinsky suzuki tartini telemann tchaikovsky
trowell vaughan-williams verdi villa-lobos vivaldi wagner weber werner ysaye rimsky-korsakov speer lago
galamian deckert caccini genischta martini miaskowsky ropartz rozycki stradella varelas wachs pachelbel battanchon
bobrowicz jacobowsky flesch sevcik feuillard mooney schroeder gershwin offenbach osbourne
""".split())
# Spellings and mangled names in downloads -> the surname used here
ALIASES = {"tchaikowsky": "tchaikovsky", "tschaikowsky": "tchaikovsky", "ajkovskij": "tchaikovsky", "cajkovskij": "tchaikovsky",
           "dvok": "dvorak", "dvorak": "dvorak", "faur": "faure", "saint-sans": "saint-saens", "rachmaninov": "rachmaninoff",
           "schostakowitsch": "shostakovich", "chopins": "chopin", "prokofieff": "prokofiev"}
# Famous works whose file names often leave out the composer
WORKS = [(r"nutcracker|swan lake|1812", "tchaikovsky"), (r"danse macabre", "saint-saens"), (r"rhapsody in blue", "gershwin"),
         (r"\bla mer\b", "debussy"), (r"cello suite no|suite no\.? ?1 for solo cello|bwv ?100[7-9]|bwv ?101[0-2]", "bach")]
# Given names that go with a surname in a file name ("frederic-chopin", "Pyotr_Ilyich_Tchaikovsky")
GIVEN = set("""
frederic francois f gustav sergei pyotr ptr ili ilyich antonin antonn claude gabriel camille johann sebastian j s js
wolfgang amadeus ludwig van d dmitri david julius nikolai w h edward felix franz giuseppe george max ozzy
""".split())
# Library prefixes that are not composers to look for in a file name (they are common words or initials)
_NOT_SURNAMES = {"strings", "version", "solo", "part", "clef", "institute", "david", "music", "suite", "cello", "unknown",
                 "exercises", "excerpts", "traditional", "the", "la", "le", "de", "di", "da", "von", "van"}
# Words around a name that are not first names ("Symphony No 5 ... Pyotr Ilyich Tchaikovsky")
_NOT_NAMES = {"symphony", "sonata", "concerto", "suite", "no", "op", "opus", "movt", "mvt", "movement", "cello",
              "violin", "viola", "piano", "for", "and", "in", "the", "of", "major", "minor", "part", "score"}
# Instruments a file name may end with: the part the file is
_PARTS = {"cello": "cello", "violoncello": "cello", "violoncelle": "cello", "violin": "violin", "viola": "viola",
          "piano": "piano", "flute": "flute", "clarinet": "clarinet", "oboe": "oboe", "bassoon": "bassoon",
          "horn": "horn", "trumpet": "trumpet", "guitar": "guitar", "harp": "harp"}
# Pieces with no composer get the kind of piece as the first half of their id, e.g. exercises_major-scales-2-octave
_NO_COMPOSER = [("exercises", r"scales?|arpeggios?|double stops|exercises?|etudes?|études?|studies|method|technique"
                 r"|bow(ing)?|warm[- ]?ups?|level"),
                ("excerpts", r"excerpts?"), ("traditional", r"folk|traditional|trad\\b|carols?|hymns?")]
# Catalogue numbers that name their composer
_CATALOGUES = {"bwv": "bach", "rv": "vivaldi", "hwv": "handel", "hob": "haydn", "kv": "mozart", "twv": "telemann"}
_NUMBER_WORDS = {"op", "no", "nr", "bwv", "k", "kv", "rv", "hob", "d", "vol", "woo", "opus", "s", "l", "hwv", "twv"}


def strip_number(stem: str) -> str:
    return re.sub(r"^\s*\d+\s*[-.)]\s*", "", stem)  # "74 - Mozart ..." -> "Mozart ..."


def initials(first: str) -> str:
    """'Johann Sebastian' -> 'js', 'J.S' -> 'js', 'CPE' -> 'cpe', 'Fr' -> 'f', 'Ludwig van' -> 'l'."""
    out = ""
    for tok in re.split(r"[\s.\-]+", unicodedata.normalize("NFKD", first)):
        tok = re.sub(r"[^A-Za-z]", "", tok)
        if not tok or tok.lower() in PARTICLES:
            continue
        out += tok.lower() if tok.isupper() and len(tok) <= 4 else tok[0].lower()
    return out


@dataclass
class Name:
    composer: str  # "Bach, Johann Sebastian" as written, or ""
    surname: str  # slug
    first: str  # initials
    title: str  # what is left of the file name
    variant: str


def _clean(stem: str) -> tuple[str, bool]:
    """A file name as words: "Dvorak_Cello_Concerto" -> "Dvorak Cello Concerto", download noise taken off.
    Returns (text, numbered): numbered when it started with a track number ("02 - ...")."""
    text = re.sub(r"\s*\(\d\)$", "", stem.strip())  # "Aerials (1)": a second download of the same file
    while (m := re.match(r"^(IMSLP\d+|PMLP\d+|\d{5,})[-_ ]+", text, flags=re.IGNORECASE)):
        text = text[m.end():]  # IMSLP and download-site numbers
    text = re.sub(r"-{2,}", " - ", text.replace("_", " ").replace("+", " "))
    if " " not in text.strip():
        text = re.sub(r"(?<=[A-Za-z0-9])-(?=[A-Za-z])|(?<=[A-Za-z])-(?=\d)", " ", text)  # "holst-the-planets-op-32"
    numbered_text = strip_number(text).strip()
    return re.sub(r"\s+", " ", numbered_text), numbered_text != text.strip()


def _plausible_name(last: str, first: str) -> bool:
    """Whether "Last, First" from a file name looks like a person, not text read from a scan ("Ani), New")."""
    ok = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'.\- ]*$")
    if not (ok.match(last.strip()) and ok.match(first.strip())):
        return False
    words = {w.lower().strip(".") for w in f"{last} {first}".split()}
    return len(last.strip()) >= 2 and not words & (_NOT_NAMES | {"scales", "volume", "institute", "music", "archives"})


def _surname(word: str, known: set[str]) -> str | None:
    cand = slug(word.removesuffix("'s"))
    cand = ALIASES.get(cand, cand)
    return cand if cand in known else None


def find_composer(text: str, known: set[str]) -> tuple[str, str] | None:
    """(surname slug, the text without the composer) for a known composer named anywhere in text, by a
    catalogue number (BWV) or by a famous work (Nutcracker)."""
    words = text.split(" ")
    for i in range(len(words)):
        for n in (2, 1):
            if i + n > len(words):
                continue
            cand = _surname(" ".join(words[i : i + n]), known)
            if not cand:
                continue
            start, end = i, i + n
            while start > 0 and (slug(words[start - 1]) in GIVEN or re.fullmatch(r"([A-Za-z]\.)+[A-Za-z]?\.?", words[start - 1])):
                start -= 1  # "Pyotr Ilyich Tchaikovsky", "frederic chopin": the given names go too
            while end < len(words) and slug(words[end]) in GIVEN and end + 1 < len(words) and _surname(words[end + 1], known):
                end += 1
            rest = [w for w in words[:start] + words[end:] if _surname(w, known) != cand]
            while rest and (slug(rest[-1]) in GIVEN or re.fullmatch(r"([A-Za-z]\.)+[A-Za-z]?\.?", rest[-1])):
                rest.pop()  # "... Gustav", "... J.S."
            title = re.sub(r"^\s*[-–,.]+\s*|\s*[-–,.(]+\s*$", "", " ".join(rest))
            return cand, re.sub(r"\s+-\s+-\s+", " - ", title).strip() or text
    for word in words:  # "gershwinanamericaninparisfullscore": a name glued to the title
        low = slug(word)
        for name in known:
            if len(name) >= 6 and low.startswith(name) and len(low) > len(name) + 3:
                return name, text
    cat = re.search(r"\b(" + "|".join(_CATALOGUES) + r")\s*\.?\s*\d", text, re.IGNORECASE)
    if cat and _CATALOGUES[cat.group(1).lower()] in known:
        return _CATALOGUES[cat.group(1).lower()], text
    for pattern, name in WORKS:
        if re.search(pattern, text, re.IGNORECASE) and name in known:
            return name, text
    return None


def no_composer(title: str) -> str:
    """The first half of the id for a piece without a composer: exercises (scales too), excerpts, traditional or unknown."""
    for kind, pattern in _NO_COMPOSER:
        if re.search(rf"\b({pattern})\b", title, re.IGNORECASE):
            return kind
    return "unknown"


def parse(parts: tuple[str, ...], stem: str, known: set[str] | None = None) -> Name:
    """Reads composer, title and part from where a file is and what it is called.

    "Bach, Johann Sebastian/Bach, Johann Sebastian - Cello Suite No.1 C.pdf" -> bach / js / Cello Suite No.1 / cello
    "Compilations/.../02 - Bartok Concerto for Orchestra-1.pdf"            -> bartok / Concerto for Orchestra excerpt 1
    "Major Scales - 2 Octave.pdf" (no composer)                               -> exercises / Major Scales - 2 Octave
    """
    known = COMPOSERS if known is None else known
    folder = parts[0] if len(parts) > 1 else ""
    text, numbered = _clean(stem)
    composer = ""
    m = re.match(r"^([^,]+),(.+?)\s+-\s+(.+)$", text)  # "Last, First - Title": the name as written beats a garbled folder name
    if m and _plausible_name(m.group(1), m.group(2)):
        composer, text = f"{m.group(1).strip()},{m.group(2)}".strip(), m.group(3).strip()
    elif "," in folder and _plausible_name(*folder.split(",", 1)):
        composer = folder
        pre, sep, rest = text.partition(" - ")  # "di Lasso - I know a Young Maiden" in "Lasso, di"
        if sep and slug(folder.split(",")[0]) in slug(pre).split("-"):
            text = rest.strip()
    elif m and slug(m.group(1)).split("-")[0] in known:  # "Squire.(Triste.), W. H - At Twilight"
        composer, text = "", m.group(3).strip()
        return _finish(Name("", slug(m.group(1)).split("-")[0], "", text, "score"), numbered)
    elif m:  # a "Last, First" that is not a name: keep the words as the title
        text = f"{m.group(1)} {m.group(2)} {m.group(3)}"
        text = re.sub(r"[^\w\s.'&()-]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
    variant, text = _part_and_excerpt(text, numbered)
    if composer:
        last, _, first = composer.partition(",")
        surname, first = slug(last) or "unknown", initials(first)
    else:
        found = find_composer(text, known)
        if found:
            surname, text = found
            first = ""
        else:  # scale sheets, exercises and the like have no composer
            surname, first = no_composer(text), ""
    return Name(composer, surname, first, text, variant)


def _finish(name: Name, numbered: bool) -> Name:
    name.variant, name.title = _part_and_excerpt(name.title, numbered)
    return name


def _part_and_excerpt(text: str, numbered: bool) -> tuple[str, str]:
    """(variant, title): the part a file is ("... Cello", "Op.65P"), and "excerpt N" for a split file ("...-5")."""
    variant = "score"
    text = re.sub(r"\s+P\s*&\s*C$", "", text)  # "P & C": piano and cello, i.e. the whole score
    pm = re.match(r"^(.*?)(?:\s+|(?<=[\d.]))([CP])$", text)  # "Op.65P", "Op. 31 C": the piano or cello part
    wm = re.match(r"^(.*\S)[\s-]+(" + "|".join(_PARTS) + r")$", text, re.IGNORECASE)
    if pm and pm.group(1):
        text, variant = pm.group(1).rstrip(" .,-"), "cello" if pm.group(2) == "C" else "piano"
    elif (wm and wm.group(1).split()[-1].lower() not in {"for", "and", "solo", "et", "pour", "violoncelle", "&", "para", "per", "fur", "für"}
          and wm.group(1).split()[-1].lower() not in _PARTS  # "... violin cello": a duo, so the score
          and not re.search(r"orchestra|quartet|quintet|trio|ensemble|choir", wm.group(1), re.IGNORECASE)):
        text, variant = wm.group(1).rstrip(" .,-"), _PARTS[wm.group(2).lower()]
    else:
        sm = re.search(r"\bfor (" + "|".join(_PARTS) + r") solo\b", text, re.IGNORECASE)
        if sm and _PARTS[sm.group(1).lower()] != "cello":
            variant = _PARTS[sm.group(1).lower()]  # a violin piece among the cello downloads
    # "Bartok Concerto for Orchestra-5": excerpt 5. After a digit only in numbered files ("34 - ... mvt 4-1"),
    # since "Op.4 nos. 1-5" is a range; never after "Op", "No", "BWV"...
    em = re.match(r"^(.*[A-Za-z)])-(\d{1,2})$", text) or (numbered and re.match(r"^(.*\S)-(\d{1,2})$", text))
    if em and re.split(r"[\s.-]+", em.group(1).lower())[-1] not in _NUMBER_WORDS:
        text = f"{em.group(1)} excerpt {em.group(2)}"
    return variant, text


def title_slug(text: str) -> str:
    s = slug(text) or "untitled"
    if len(s) > MAX_TITLE:
        s = s[:MAX_TITLE].rsplit("-", 1)[0]
    return s


def scan(lib: Library) -> list[Path]:
    out = []
    for p in sorted(lib.root.rglob("*")):
        rel = p.relative_to(lib.root)
        if len(rel.parts) > 1 and rel.parts[0] in SKIP_TOP:
            continue
        if p.is_file() and p.suffix.lower() in SCORE_EXT:
            out.append(p)
    return out


_KINDS_WITHOUT_COMPOSER = ("unknown", "exercises", "excerpts", "traditional")
_NOT_A_COMPOSER = {"composer", "unknown", "anonymous", "administrator", "user", "owner", "musescore", "finale", "sibelius software",
                   "copyright", "arranger", "transcribed", "public domain"}


def _musicxml_root(path: Path):
    import xml.etree.ElementTree as ET
    import zipfile

    if path.suffix.lower() == ".mxl":
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            root_file = ""
            if "META-INF/container.xml" in names:
                for el in ET.fromstring(zf.read("META-INF/container.xml")).iter():
                    if el.tag.endswith("rootfile") and el.get("full-path"):
                        root_file = el.get("full-path", "")
                        break
            if root_file not in names:
                root_file = next((n for n in names if n.lower().endswith((".xml", ".musicxml")) and not n.startswith("META-INF")), "")
            return ET.fromstring(zf.read(root_file)) if root_file else None
    return ET.parse(path).getroot()


def _composer_part(text: str) -> str:
    """The composer in a credit: "Chopin arr. Austin Harning" -> "Chopin", "Ludwig van Beethoven (1770-1827)" ->
    "Ludwig van Beethoven", "W.H. Squire, arr. Daniel E." -> "W.H. Squire". "" for a placeholder or an arranger alone."""
    text = re.split(r"arr\.|\barr\b|\b(arranged|arrangement|transcri\w*|trascri\w*|orch\w*|adapted|edited|ed\.|after)\b|/", text, flags=re.IGNORECASE)[0]
    text = re.sub(r"\([^)]*\)|\b\d{3,4}\b|[–-]\s*$", " ", text)
    text = re.sub(r"^\s*(music by|by|composer:?|words and music by)\s+", "", text, flags=re.IGNORECASE)
    text = " ".join(text.replace(",", " , ").split()).strip(" ,.-–")
    text = text.replace(" , ", ", ")
    if not re.search(r"[A-Za-zÀ-ÿ]{3}", text) or text.lower() in _NOT_A_COMPOSER or re.search(r"composer|arranger", text, re.IGNORECASE):
        return ""
    return text if len(text.split()) <= 5 else ""


def embedded_composer(path: Path, known: set[str]) -> str:
    """The composer a score file names inside itself: MusicXML's <creator type="composer"> (or a composer named
    in its credits), a PDF's author field, or a known composer printed on a PDF's first page. "" if none.
    Arrangers and transcribers are left out ("Chopin arr. X" gives Chopin)."""
    texts: list[str] = []
    try:
        if path.suffix.lower() in (".mxl", ".musicxml", ".xml"):
            root = _musicxml_root(path)
            if root is None:
                return ""
            creator = ""
            for el in root.iter():
                tag = el.tag.rsplit("}", 1)[-1]
                if tag == "creator" and el.get("type", "composer") == "composer" and (el.text or "").strip() and not creator:
                    creator = _composer_part(" ".join(el.text.split()))
                if tag == "credit-words" and el.text:
                    texts.append(el.text)
            # a well-known composer in the printed credits beats the creator field, which is often the arranger
            from_credits = _known_in(texts)
            return from_credits or creator
        elif path.suffix.lower() == ".pdf":
            import logging

            from pypdf import PdfReader

            logging.getLogger("pypdf").setLevel(logging.ERROR)  # damaged downloads warn a lot

            reader = PdfReader(str(path))
            if reader.is_encrypted:
                reader.decrypt("")  # most "encrypted" sheet music only forbids editing
            author = (reader.metadata or {}).get("/Author") if reader.metadata else None
            if author:
                texts.append(str(author))
            if reader.pages:
                texts.append((reader.pages[0].extract_text() or "")[:1500])
    except Exception:  # an unreadable file just has no details
        return ""
    return _known_in(texts)


def _known_in(texts: list[str]) -> str:
    """A well-known composer (the built-in list only: names from the library can be title words) named on a line
    of credits or title-page text, without any arranger."""
    for text in texts:
        for line in text.splitlines():
            line = _composer_part(" ".join(re.sub(r"[_+]", " ", line).split()))
            found = find_composer(line, COMPOSERS) if line else None
            if found and len(line) < 60 and any(_surname(w, COMPOSERS) for w in re.split(r"[\s,]+", line)):
                return found[0].title()  # "CAN CAN, OFFENBACH" -> "Offenbach"
    return ""


def _surname_of(name: str) -> str:
    """'Pyotr Ilyich Tchaikovsky' -> 'tchaikovsky', 'Bach, J.S.' -> 'bach', 'Hidetoshi Sato' -> 'sato'."""
    name = re.sub(r"\([^)]*\)|\d+", " ", name)
    if "," in name:
        return slug(name.split(",")[0])
    words = [w for w in re.split(r"\s+", name.strip()) if w and slug(w) not in GIVEN and not w.endswith(".")]
    last = slug(words[-1]) if words else slug(name)
    return ALIASES.get(last, last)


_IGNORED = {"in", "for", "and", "the", "of", "a", "no", "op", "cello", "violoncello", "major", "minor", "score", "part", "excerpt"}


def _words(title: str) -> set[str]:
    return {w for w in slug(title).split("-") if w not in _IGNORED}


def _library_prefixes(lib: Library) -> tuple[dict[str, str], dict[str, set[str]]]:
    """From pieces/: composer prefix by surname ("bach" -> "bach-js", the most used), and title words by piece id."""
    counts: dict[str, dict[str, int]] = {}
    titles: dict[str, set[str]] = {}
    for folder in lib.folders():
        prefix, _, title = folder.name.partition("_")
        titles[folder.name] = _words(title)
        for key in {prefix, prefix.split("-")[0]}:
            counts.setdefault(key, {}).setdefault(prefix, 0)
            counts[key][prefix] += 1
    best = {k: (k if k in v else max(v, key=lambda p: v[p])) for k, v in counts.items()}
    return best, titles


def _similar(pid: str, titles: dict[str, set[str]]) -> str | None:
    """A piece already in pieces/ by the same composer whose title has nearly the same words."""
    prefix, _, title = pid.partition("_")
    mine = _words(title)
    if not mine or prefix in _KINDS_WITHOUT_COMPOSER:
        return titles.get(pid) is not None and pid or None
    for other, words in titles.items():
        if other.split("_")[0].split("-")[0] != prefix.split("-")[0] or not words:
            continue
        if len(mine & words) / len(mine | words) >= 0.6 or other == pid:
            return other
    return None


def plan(lib: Library, fresh: bool = False) -> tuple[Path, int]:
    """Writes organize-plan.csv, keeping the rows of a plan already there (so edits survive a re-run) unless
    `fresh`. Files already moved (in organize-log.csv) are never planned again.

    Rows marked "check" are not moved by apply: a second download of the same file, a file that looks like a piece
    already in pieces/, or a scan without a name. The note column says which; change action to "move" to file it."""
    path = lib.root / PLAN
    old = {} if fresh else {r["source"]: r for r in read_csv(path)}
    files = scan(lib)
    prefixes, titles = _library_prefixes(lib)
    # composers the library already has, by the composer column of catalog.csv (piece ids alone are not enough:
    # some begin with a title word, like "can-can_")
    try:
        filed = {_surname_of(r.get("composer", "")) for r in lib.catalog() if r.get("composer", "").strip()}
    except Exception:
        filed = set()
    from_lib = filed | set(prefixes)
    known = COMPOSERS | {k for k in from_lib if len(k) >= 4 and k not in _NOT_SURNAMES and k not in GIVEN}
    names = {p: parse(p.relative_to(lib.root).parts, p.stem, known) for p in files}
    # a surname shared by composers with different first names (the Bachs, the Rombergs) gets their initials
    firsts: dict[str, set[str]] = {}
    for n in names.values():
        if n.first:
            firsts.setdefault(n.surname, set()).add(n.first)
    families = {s for s, f in firsts.items() if len(f) > 1}
    rows: list[dict[str, str]] = []
    taken: set[tuple[str, str, str]] = set()  # (piece_id, variant, ext) already planned
    for r in old.values():
        taken.add((r["piece_id"], r["variant"], Path(r["source"]).suffix.lower()))
    stems = {(p.parent, p.stem.lower(), p.suffix.lower()) for p in files}
    for p in files:
        rel = p.relative_to(lib.root).as_posix()
        if rel in old:
            rows.append(old[rel])
            continue
        parts = p.relative_to(lib.root).parts
        batch = parts[0] if len(parts) > 1 else "(top folder)"
        nm = names[p]
        from_inside = ""
        if nm.surname in _KINDS_WITHOUT_COMPOSER and rel not in old:
            from_inside = embedded_composer(p, known)
            if from_inside and _surname_of(from_inside):
                nm.composer, nm.surname = from_inside, _surname_of(from_inside)
        if nm.first and f"{nm.surname}-{nm.first}" in prefixes:
            comp = f"{nm.surname}-{nm.first}"  # the library already has this composer with initials
        elif nm.surname in families and nm.first:
            comp = f"{nm.surname}-{nm.first}"
        else:
            comp = prefixes.get(nm.surname, nm.surname) if nm.surname not in _KINDS_WITHOUT_COMPOSER else nm.surname
        pid = f"{comp}_{title_slug(nm.title)}"
        variant = nm.variant
        ext = p.suffix.lower()
        action, note = "move", ""
        copy = re.match(r"^(.*?)\s*\(\d\)$", p.stem)
        if copy and (p.parent, copy.group(1).lower(), ext) in stems:
            action, note = "check", f"second download of {copy.group(1)}{p.suffix}"
        elif (same := _similar(pid, titles)):
            action, note = "check", f"may already be in the library as {same}"
        elif re.fullmatch(r"(img|scan|image|doc)[\s_-]*\d+", p.stem, re.IGNORECASE):
            action, note = "check", "a scan without a name: open it and give it one"
        elif comp == "unknown":
            note = "no composer found: add one to piece_id and composer if it has one"
        elif from_inside:
            note = f"composer from inside the file: {from_inside}"
        n, base = 2, variant
        while (pid, variant, ext) in taken:  # two files would get the same name: number the later one
            variant, n = f"{base}-{n}", n + 1
        taken.add((pid, variant, ext))
        rows.append({"batch": batch, "source": rel, "piece_id": pid, "variant": variant, "action": action,
                     "composer": nm.composer, "title": nm.title, "note": note})
    rows.sort(key=lambda r: (r["batch"], r["source"]))
    write_csv(path, PLAN_COLUMNS, rows)
    return path, len(rows)


def batches(lib: Library) -> dict[str, tuple[int, int]]:
    """Batch -> (files still to move, files moved)."""
    moved = {r["source"] for r in read_csv(lib.root / LOG) if r.get("moved") == "yes"}
    out: dict[str, tuple[int, int]] = {}
    for r in read_csv(lib.root / PLAN):
        if r["action"].strip().lower() != "move":
            continue
        todo, done = out.get(r["batch"], (0, 0))
        out[r["batch"]] = (todo, done + 1) if r["source"] in moved else (todo + 1, done)
    return out


def apply(lib: Library, batch: str, rebuild: bool = True) -> tuple[list[str], list[str]]:
    """Moves one batch. Returns (moved, problems). Checks every row first, so a bad id moves nothing."""
    rows = [r for r in read_csv(lib.root / PLAN) if r["batch"] == batch and r["action"].strip().lower() == "move"]
    if not rows:
        raise ValueError(f"no files to move in batch '{batch}' (see {PLAN})")
    done = {r["source"] for r in read_csv(lib.root / LOG) if r.get("moved") == "yes"}
    problems, todo = [], []
    seen: set[Path] = set()
    for r in rows:
        if r["source"] in done:
            continue
        src = lib.root / r["source"]
        pid, var = r["piece_id"].strip(), r["variant"].strip()
        dest = lib.pieces / pid / f"{pid}__{var}{src.suffix.lower()}"
        if not ID_RE.match(pid):
            problems.append(f"{r['source']}: piece_id '{pid}' should be composer_title (lowercase, hyphens)")
        elif not VARIANT_RE.match(var):
            problems.append(f"{r['source']}: variant '{var}' should be lowercase words joined by hyphens")
        elif not src.is_file():
            problems.append(f"{r['source']}: not found")
        elif dest.exists() or dest in seen:
            problems.append(f"{r['source']}: {dest.relative_to(lib.root).as_posix()} would be taken twice")
        else:
            seen.add(dest)
            todo.append((r, src, dest))
    if problems:
        return [], problems
    log_new = not (lib.root / LOG).is_file()
    cat_rows = []
    moved = []
    today = datetime.date.today().isoformat()
    for r, src, dest in todo:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), dest)
        entries = [{"batch": batch, "source": r["source"], "dest": dest.relative_to(lib.root).as_posix(), "moved": "yes"}]
        report = src.with_name(f"{src.stem}.quality.json")  # Lento_ConvertPDF's quality report travels with its file
        if report.is_file() and not dest.with_name(f"{dest.stem}.quality.json").exists():
            shutil.move(str(report), dest.with_name(f"{dest.stem}.quality.json"))
            entries.append({"batch": batch, "source": report.relative_to(lib.root).as_posix(),
                        "dest": dest.with_name(f"{dest.stem}.quality.json").relative_to(lib.root).as_posix(), "moved": "yes"})
        moved.append(dest.relative_to(lib.root).as_posix())
        if dest.suffix == ".pdf":
            row = {c: "" for c in COLUMNS}
            row.update(piece_id=r["piece_id"].strip(), file=dest.name, variant=r["variant"].strip(), composer=r.get("composer", ""),
                       title=r.get("title", ""), source=r["source"], added=today)
            # no page count: reading every PDF would download the whole library from Drive
            cat_rows.append(row)
        with (lib.root / LOG).open("a", newline="", encoding="utf-8-sig" if log_new else "utf-8") as f:
            w = csv.DictWriter(f, fieldnames=LOG_COLUMNS)  # after every move, so a crash leaves an exact record
            if log_new:
                w.writeheader()
                log_new = False
            w.writerows(entries)
    for folder in sorted({src.parent for _, src, _ in todo}, key=lambda d: -len(d.parts)):
        while folder != lib.root and folder.is_dir() and not any(folder.iterdir()):  # emptied folders go (undo remakes them)
            folder.rmdir()
            folder = folder.parent
    lib.append_catalog(cat_rows)
    if rebuild:
        lib.write_index()
    return moved, []


def undo(lib: Library, batch: str) -> list[str]:
    """Moves a batch's files back and drops their catalog rows. Returns what was put back."""
    log = read_csv(lib.root / LOG)
    back, names = [], set()
    for r in log:
        if r["batch"] != batch or r.get("moved") != "yes":
            continue
        dest, src = lib.root / r["dest"], lib.root / r["source"]
        if dest.is_file() and not src.exists():
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), src)
            r["moved"] = "undone"
            back.append(r["source"])
            names.add(dest.name)
            if dest.parent.is_dir() and not any(dest.parent.iterdir()):
                dest.parent.rmdir()
    write_csv(lib.root / LOG, LOG_COLUMNS, log)
    if names and lib.catalog_path.is_file():
        rows = [r for r in lib.catalog() if r["file"] not in names]
        lib.write_catalog(rows)
    if (lib.root / INDEX_NAME).exists() or back:
        lib.write_index()
    return back


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [{k: (v or "") for k, v in r.items() if k} for r in csv.DictReader(f)]


def write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel reads accents right
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)
