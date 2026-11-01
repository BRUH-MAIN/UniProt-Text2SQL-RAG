-- Semantics the DDL alone cannot convey. Stored as COMMENTs so they live next to the schema,
-- are readable with \d+ in psql, and are what the SQL agent's describe_table tool returns.
-- Each statement documents what ingest/parse_and_load.py actually does, including its gaps.

COMMENT ON TABLE proteins IS 'One row per UniProt Swiss-Prot (reviewed) entry.';
COMMENT ON COLUMN proteins.entry IS 'Primary UniProt accession, e.g. P04637. Unique.';
COMMENT ON COLUMN proteins.entry_name IS 'UniProt entry name, e.g. P53_HUMAN.';
COMMENT ON COLUMN proteins.organism IS 'Full UniProt organism string including the common name in brackets, e.g. ''Homo sapiens (Human)''. Do not compare to ''Homo sapiens'' with =.';
COMMENT ON COLUMN proteins.protein_names IS 'Recommended and alternative names joined with ''; ''. Search with ILIKE.';
COMMENT ON COLUMN proteins.sequence IS 'Amino-acid sequence, one letter per residue. Use length(sequence) for its length.';

COMMENT ON TABLE functions IS 'FUNCTION annotation, free text. A protein may have zero, one or several rows.';
COMMENT ON TABLE subcellular_locations IS 'SUBCELLULAR LOCATION annotation, free text split on '';''. Values look like ''Nucleus.'' or ''Multi-pass membrane protein.'' with inconsistent trailing periods: match with ILIKE ''%...%'', not =.';
COMMENT ON TABLE disease_involvement IS 'DISEASE annotation. disease_name includes the abbreviation, e.g. ''Cystic fibrosis (CF)''. disease_name and omim_id are NULL when the source text did not match the expected pattern; description is then the only populated field.';
COMMENT ON TABLE biotechnological_uses IS 'BIOTECHNOLOGY annotation, free text. Sparse: few proteins have one.';
COMMENT ON TABLE pharmaceutical_uses IS 'PHARMACEUTICAL annotation, free text. Sparse.';
COMMENT ON TABLE toxic_doses IS 'TOXIC DOSE annotation. Sparse and may be empty for a given dataset.';
COMMENT ON COLUMN toxic_doses.measurement_unit IS 'Never populated by the loader (always NULL).';
COMMENT ON TABLE allergenic_properties IS 'ALLERGEN annotation, free text. Sparse.';

COMMENT ON TABLE interactions IS 'Binary interactions from the INTERACTION annotation.';
COMMENT ON COLUMN interactions.interacting_protein IS 'Free text ''GENE (ACCESSION)'' of the partner, e.g. ''MDM2 (Q00987)''. Not a foreign key: join to proteins on the accession substring only if you must.';
COMMENT ON COLUMN interactions.interaction_type IS 'NOT a category. Holds the number of supporting experiments as text, ''NbExp=<n>''. Extract the number with substring(interaction_type from ''[0-9]+'')::int.';

COMMENT ON TABLE taxonomic_lineage IS 'One row per lineage level per protein. Identical for all proteins of the same species, so it is not useful for distinguishing proteins.';
COMMENT ON COLUMN taxonomic_lineage.rank_order IS '0 = highest rank (e.g. Eukaryota); increases toward the species.';
COMMENT ON COLUMN taxonomic_lineage.lineage_path IS 'A SINGLE taxon name at this rank, not a path.';

COMMENT ON TABLE active_sites IS 'ACT_SITE features.';
COMMENT ON COLUMN active_sites.position IS 'Residue number stored as TEXT. Cast with position::int before comparing numerically.';
COMMENT ON TABLE binding_sites IS 'BINDING features: residue range start_position..end_position and the bound ligand (e.g. ''Zn(2+)'', ''ATP'', ''NADP(+)'').';
COMMENT ON TABLE mutagenesis IS 'MUTAGEN features (experimental amino-acid substitutions).';
COMMENT ON COLUMN mutagenesis.original_residue IS 'One-letter code(s); can be several residues, e.g. ''KDQ''.';
COMMENT ON COLUMN mutagenesis.mutated_residue IS 'One-letter code(s) the residue(s) were changed to, e.g. ''A'' = alanine.';
COMMENT ON COLUMN mutagenesis.description IS 'The observed effect of the mutation, as free text. This is where the result of the experiment is recorded.';
COMMENT ON COLUMN mutagenesis.effect IS 'Never populated by the loader (always NULL). Use description for the observed effect.';
COMMENT ON TABLE topological_domains IS 'TOPO_DOM features, e.g. ''Cytoplasmic'', ''Extracellular''.';
COMMENT ON COLUMN topological_domains.description IS 'Never populated by the loader (always NULL).';

COMMENT ON TABLE genes IS 'Gene names including synonyms. There is no primary/synonym flag, so one name can map to several unrelated proteins (e.g. a synonym shared with another gene).';
COMMENT ON TABLE protein_genes IS 'Junction: proteins <-> genes.';
COMMENT ON TABLE pathways IS 'PATHWAY annotation as free text including step detail, e.g. ''Protein modification; protein ubiquitination.'' (note the trailing period). Look up the exact spelling with search_values before using =.';
COMMENT ON TABLE protein_pathways IS 'Junction: proteins <-> pathways.';
COMMENT ON TABLE protein_families IS 'Family names taken from the ''Belongs to the ...'' sentence, e.g. ''protein kinase superfamily'', ''p53 family'' (often lower-case).';
COMMENT ON TABLE protein_family_memberships IS 'Junction: proteins <-> protein_families.';
