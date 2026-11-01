"""Parse a UniProt Swiss-Prot flat file and load it into the Postgres schema.

Usage:
    python -m ingest.parse_and_load
    python -m ingest.parse_and_load --input data/uniprot_subset.dat.gz --limit 12000
    python -m ingest.parse_and_load --truncate   # wipe existing protein data first

Design notes:
- Bio.SwissProt.parse() is a lazy generator - records are never all loaded into
  memory at once, so this comfortably handles 10k+ entries.
- map_record() is a pure function (record in, plain dicts out) with no DB
  dependency - it's the part covered by tests/test_parse_sample.py.
- Comment/feature routing is heuristic regex extraction over UniProt free
  text. It won't be 100% precise for every edge case (e.g. INTERACTION and
  SIMILARITY parsing) - acceptable for this project's scope.
"""
import argparse
import gzip
import itertools
import os
import re
from pathlib import Path
from typing import Any, Iterator

import psycopg
from Bio import SwissProt
from dotenv import load_dotenv

load_dotenv()

DEFAULT_INPUT = Path(__file__).parent.parent / "data" / "uniprot_subset.dat.gz"
DEFAULT_LIMIT = int(os.environ.get("INGEST_LIMIT", "12000"))
BATCH_SIZE = 500

_EVIDENCE_RE = re.compile(r"\{ECO:[^}]*\}")
_WHITESPACE_RE = re.compile(r"\s+")
_NAME_RE = re.compile(r"(?:Full|Short)=([^;{]+)")
_DISEASE_RE = re.compile(r"^(?P<name>.*?)\s*\[MIM:(?P<mim>\d+)\]:\s*(?P<desc>.*)$", re.DOTALL)
_INTERACTION_RE = re.compile(r"(\S+):\s*(\S+);\s*NbExp=(\d+)")
_SIMILARITY_RE = re.compile(r"Belongs to the (.+?)\.")
_COMMENT_RE = re.compile(r"^([A-Z][A-Z \-]*):\s?(.*)$", re.DOTALL)
_MUTAGEN_RE = re.compile(r"^([A-Za-z]+)->([A-Za-z,]+):\s*(.*)$", re.DOTALL)


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    text = _EVIDENCE_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = re.sub(r"\s+([.,;:])", r"\1", text)  # no space before punctuation
    text = re.sub(r"\.{2,}", ".", text)  # collapse repeated periods left by tag removal
    return text or None


def _extract_protein_names(description: str) -> str | None:
    names = [_clean(m) for m in _NAME_RE.findall(description)]
    names = [n for n in dict.fromkeys(names) if n]
    return "; ".join(names) if names else None


def _split_comment(comment: str) -> tuple[str, str] | None:
    m = _COMMENT_RE.match(comment)
    if not m:
        return None
    return m.group(1).strip(), m.group(2)


def _position(location) -> tuple[int | None, int | None]:
    """Return 1-based (start, end), or (None, None) if either boundary is
    unknown (UniProt "?" positions, e.g. on fragmentary/uncharacterized termini)."""
    try:
        return int(location.start) + 1, int(location.end)
    except TypeError:
        return None, None


def _parse_mutagen(note: str) -> tuple[str | None, str | None, str]:
    note = note or ""
    m = _MUTAGEN_RE.match(note)
    if m:
        return m.group(1), m.group(2), _clean(m.group(3)) or ""
    if note.startswith("Missing"):
        return None, None, _clean(note[len("Missing"):].lstrip(":").strip()) or note
    return None, None, _clean(note) or note


def map_record(record: "SwissProt.Record") -> dict[str, Any]:
    """Convert a parsed Bio.SwissProt.Record into plain dicts/lists ready for
    insertion, keyed by target table name. Pure function, no DB access."""

    protein = {
        "entry": record.accessions[0],
        "entry_name": record.entry_name,
        "organism": (record.organism or "").rstrip("."),
        "protein_names": _extract_protein_names(record.description),
        "sequence": record.sequence,
    }

    functions: list[dict] = []
    subcellular_locations: list[dict] = []
    disease_involvement: list[dict] = []
    biotechnological_uses: list[dict] = []
    pharmaceutical_uses: list[dict] = []
    toxic_doses: list[dict] = []
    allergenic_properties: list[dict] = []
    interactions: list[dict] = []
    pathways: list[str] = []
    protein_families: list[str] = []

    for comment in record.comments:
        split = _split_comment(comment)
        if split is None:
            continue
        topic, content = split

        if topic == "FUNCTION":
            if desc := _clean(content):
                functions.append({"description": desc})
        elif topic == "SUBCELLULAR LOCATION":
            for part in content.split(";"):
                if loc := _clean(part):
                    subcellular_locations.append({"location": loc})
        elif topic == "DISEASE":
            m = _DISEASE_RE.match(content)
            if m:
                disease_involvement.append({
                    "disease_name": _clean(m.group("name")),
                    "description": _clean(m.group("desc")),
                    "omim_id": m.group("mim"),
                })
            elif desc := _clean(content):
                disease_involvement.append({
                    "disease_name": None,
                    "description": desc,
                    "omim_id": None,
                })
        elif topic == "BIOTECHNOLOGY":
            if desc := _clean(content):
                biotechnological_uses.append({"description": desc})
        elif topic == "PHARMACEUTICAL":
            if desc := _clean(content):
                pharmaceutical_uses.append({"description": desc})
        elif topic == "TOXIC DOSE":
            if desc := _clean(content):
                toxic_doses.append({"dose_description": desc, "measurement_unit": None})
        elif topic == "ALLERGEN":
            if desc := _clean(content):
                allergenic_properties.append({"description": desc})
        elif topic == "INTERACTION":
            for accession, gene, nbexp in _INTERACTION_RE.findall(content):
                interactions.append({
                    "interacting_protein": f"{gene} ({accession})",
                    "interaction_type": f"NbExp={nbexp}",
                })
        elif topic == "PATHWAY":
            if name := _clean(content):
                pathways.append(name)
        elif topic == "SIMILARITY":
            m = _SIMILARITY_RE.search(content)
            if m and (name := _clean(m.group(1))):
                protein_families.append(name)

    active_sites: list[dict] = []
    binding_sites: list[dict] = []
    mutagenesis: list[dict] = []
    topological_domains: list[dict] = []

    for feat in record.features:
        start, end = _position(feat.location)
        note = feat.qualifiers.get("note")

        if feat.type == "ACT_SITE":
            active_sites.append({
                "position": str(start) if start is not None else None,
                "description": _clean(note),
            })
        elif feat.type == "BINDING":
            binding_sites.append({
                "start_position": start,
                "end_position": end,
                "ligand": feat.qualifiers.get("ligand"),
                "description": _clean(note),
            })
        elif feat.type == "MUTAGEN":
            original, mutated, desc = _parse_mutagen(note or "")
            mutagenesis.append({
                "position_start": start,
                "position_end": end,
                "original_residue": original,
                "mutated_residue": mutated,
                "description": desc,
                "effect": None,
            })
        elif feat.type == "TOPO_DOM":
            topological_domains.append({
                "domain_name": _clean(note),
                "start_position": start,
                "end_position": end,
                "description": None,
            })

    genes: list[str] = []
    for gene_entry in record.gene_name or []:
        if name := _clean(gene_entry.get("Name")):
            genes.append(name)
        for syn in gene_entry.get("Synonyms", []):
            if syn := _clean(syn):
                genes.append(syn)

    taxonomic_lineage = [
        {"rank_order": i, "lineage_path": taxon}
        for i, taxon in enumerate(record.organism_classification)
    ]

    return {
        "protein": protein,
        "functions": functions,
        "subcellular_locations": subcellular_locations,
        "disease_involvement": disease_involvement,
        "biotechnological_uses": biotechnological_uses,
        "pharmaceutical_uses": pharmaceutical_uses,
        "toxic_doses": toxic_doses,
        "allergenic_properties": allergenic_properties,
        "interactions": interactions,
        "taxonomic_lineage": taxonomic_lineage,
        "active_sites": active_sites,
        "binding_sites": binding_sites,
        "mutagenesis": mutagenesis,
        "topological_domains": topological_domains,
        "genes": genes,
        "pathways": pathways,
        "protein_families": protein_families,
    }


# ============================================================
# DB loading
# ============================================================

_DETAIL_TABLES = (
    "functions", "subcellular_locations", "disease_involvement",
    "biotechnological_uses", "pharmaceutical_uses", "toxic_doses",
    "allergenic_properties", "interactions", "taxonomic_lineage",
    "active_sites", "binding_sites", "mutagenesis", "topological_domains",
)

_MANY_TO_MANY = (
    # (record key, ref table, id column, name column, junction table)
    ("genes", "genes", "gene_id", "gene_name", "protein_genes"),
    ("pathways", "pathways", "pathway_id", "pathway_name", "protein_pathways"),
    ("protein_families", "protein_families", "family_id", "family_name", "protein_family_memberships"),
)


def _values_sql(row_count: int, col_count: int) -> str:
    row_placeholder = "(" + ", ".join(["%s"] * col_count) + ")"
    return ", ".join([row_placeholder] * row_count)


def _bulk_insert_proteins(cur, proteins: list[dict]) -> dict[str, int]:
    """Upsert a batch of protein rows in one round trip; return entry -> protein_id."""
    if not proteins:
        return {}
    columns = ["entry", "entry_name", "organism", "protein_names", "sequence"]
    params = [p[c] for p in proteins for c in columns]
    sql = f"""
        INSERT INTO proteins ({", ".join(columns)})
        VALUES {_values_sql(len(proteins), len(columns))}
        ON CONFLICT (entry) DO UPDATE SET
            entry_name = EXCLUDED.entry_name,
            organism = EXCLUDED.organism,
            protein_names = EXCLUDED.protein_names,
            sequence = EXCLUDED.sequence,
            updated_at = now()
        RETURNING entry, protein_id
    """
    cur.execute(sql, params)
    return dict(cur.fetchall())


def _bulk_insert_child_table(cur, table: str, rows_by_entry: dict[str, list[dict]],
                              entry_to_id: dict[str, int]) -> None:
    """Insert every row for `table` across a whole batch in one round trip."""
    columns: list[str] | None = None
    all_rows: list[tuple] = []
    for entry, rows in rows_by_entry.items():
        protein_id = entry_to_id.get(entry)
        if protein_id is None or not rows:
            continue
        if columns is None:
            columns = list(rows[0].keys())
        for row in rows:
            all_rows.append((protein_id, *(row[c] for c in columns)))
    if not all_rows:
        return
    col_list = ", ".join(["protein_id"] + columns)
    sql = f"INSERT INTO {table} ({col_list}) VALUES {_values_sql(len(all_rows), len(columns) + 1)}"
    cur.execute(sql, [v for row in all_rows for v in row])


def _bulk_link_many_to_many(cur, cache: dict[str, int], ref_table: str, id_col: str,
                             name_col: str, junction_table: str,
                             names_by_entry: dict[str, list[str]],
                             entry_to_id: dict[str, int]) -> None:
    all_names = {n.strip() for names in names_by_entry.values() for n in names if n and n.strip()}
    new_names = [n for n in all_names if n not in cache]
    if new_names:
        sql = (
            f"INSERT INTO {ref_table} ({name_col}) VALUES {_values_sql(len(new_names), 1)} "
            f"ON CONFLICT ({name_col}) DO UPDATE SET {name_col} = EXCLUDED.{name_col} "
            f"RETURNING {name_col}, {id_col}"
        )
        cur.execute(sql, new_names)
        cache.update(cur.fetchall())

    junction_rows: list[tuple[int, int]] = []
    for entry, names in names_by_entry.items():
        protein_id = entry_to_id.get(entry)
        if protein_id is None:
            continue
        seen: set[str] = set()
        for n in names:
            n = n.strip() if n else ""
            if not n or n in seen:
                continue
            seen.add(n)
            junction_rows.append((protein_id, cache[n]))
    if not junction_rows:
        return
    sql = (
        f"INSERT INTO {junction_table} (protein_id, {id_col}) "
        f"VALUES {_values_sql(len(junction_rows), 2)} ON CONFLICT DO NOTHING"
    )
    cur.execute(sql, [v for row in junction_rows for v in row])


def load_batch(cur, caches: dict[str, dict], batch: list[dict]) -> None:
    """Load a whole batch of mapped records in a small, fixed number of
    round trips, regardless of batch size - the naive per-protein/per-table
    approach this replaced took ~10 round trips per protein, which made
    ingesting thousands of proteins against a remote DB impractically slow."""
    entry_to_id = _bulk_insert_proteins(cur, [m["protein"] for m in batch])
    # Re-loading a protein must replace its rows, not append to them: without this a second run
    # over the same input silently doubled every detail table.
    ids = list(entry_to_id.values())
    for table in [*_DETAIL_TABLES, *(m2m[4] for m2m in _MANY_TO_MANY)]:
        cur.execute(f"DELETE FROM {table} WHERE protein_id = ANY(%s)", (ids,))
    for table in _DETAIL_TABLES:
        rows_by_entry = {m["protein"]["entry"]: m[table] for m in batch}
        _bulk_insert_child_table(cur, table, rows_by_entry, entry_to_id)
    for record_key, ref_table, id_col, name_col, junction_table in _MANY_TO_MANY:
        names_by_entry = {m["protein"]["entry"]: m[record_key] for m in batch}
        _bulk_link_many_to_many(
            cur, caches[record_key], ref_table, id_col, name_col,
            junction_table, names_by_entry, entry_to_id,
        )


def _open_input(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "rt", encoding="utf-8")


def iter_records(path: Path, limit: int) -> Iterator["SwissProt.Record"]:
    with _open_input(path) as handle:
        yield from itertools.islice(SwissProt.parse(handle), limit)


def run(input_path: Path, limit: int, truncate: bool) -> None:
    database_url = os.environ["INGEST_DATABASE_URL"]
    caches = {"genes": {}, "pathways": {}, "protein_families": {}}

    with psycopg.connect(database_url) as conn:
        if truncate:
            with conn.cursor() as cur:
                # the reference tables are not FK-children of proteins, so name them explicitly -
                # otherwise stale genes/pathways/families accumulate across truncating runs
                cur.execute("TRUNCATE proteins, genes, pathways, protein_families RESTART IDENTITY CASCADE")
            conn.commit()
            print("Truncated all protein data and reference tables.")

        count = 0
        batch: list[dict] = []
        with conn.cursor() as cur:
            for record in iter_records(input_path, limit):
                batch.append(map_record(record))
                count += 1
                if len(batch) >= BATCH_SIZE:
                    load_batch(cur, caches, batch)
                    conn.commit()
                    batch.clear()
                    print(f"\rIngested {count} proteins", end="", flush=True)
            if batch:
                load_batch(cur, caches, batch)
                conn.commit()

    print(f"\rIngested {count} proteins total.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Path to .dat or .dat.gz")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--truncate", action="store_true", help="Wipe existing protein data first")
    args = parser.parse_args()
    run(Path(args.input), args.limit, args.truncate)


if __name__ == "__main__":
    main()
