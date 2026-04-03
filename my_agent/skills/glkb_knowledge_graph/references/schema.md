# GLKB Database Schema

## Node Labels

### Article
Properties: pubmedid (STRING), title (STRING), pubdate (INTEGER/YYYY), authors (LIST), journal (STRING), source (STRING), id (STRING), preferred_id (STRING), embedding (LIST), n_citation (INTEGER), doi (STRING), abstract (STRING), author_affiliations (LIST)

### Journal
Properties: title (STRING), med_abbrevation (STRING), iso_abbrevation (STRING), issn_print (STRING), issn_online (STRING), jrid (STRING), id (STRING), impact_factor (FLOAT), preferred_id (STRING)

### Vocabulary (base type)
Subtypes that connect to Article:
- **Gene**: name, id, preferred_id, n_citation, description, synonyms, embedding, rsid, ref, alt, source
- **DiseaseOrPhenotypicFeature**: name, id, preferred_id, n_citation, description, synonyms, embedding, rsid, ref, alt, source
- **ChemicalEntity**: name, id, preferred_id, n_citation, description, synonyms, embedding, rsid, ref, alt, source
- **SequenceVariant**: id, preferred_id, n_citation, description, synonyms, embedding, rsid, ref, alt, source
- **MeshTerm**: name, id, preferred_id, n_citation, description, synonyms, embedding, rsid, ref, alt, source
- **AnatomicalEntity**: name, id, preferred_id, n_citation, description, synonyms, embedding, rsid, ref, alt, source

Subtypes that connect only to other Vocabulary:
- **Pathway**: name, id, preferred_id, n_citation, description, synonyms, embedding, source
- **BiologicalProcess**: name, id, preferred_id, n_citation, description, synonyms, embedding, source
- **CellularComponent**: name, id, preferred_id, n_citation, description, synonyms, embedding, source
- **MolecularFunction**: name, id, preferred_id, n_citation, description, synonyms, embedding, source

## Relationships

### Article relationships
- Article -> Journal: **PublishedIn** (no properties)
- Article -> Vocabulary: **ContainTerm** (source, normalized_name, type, prob)
- Article -> Article: **Cite** (source)
- Article -> Sentence: **ContainSentence** (no properties)

### Vocabulary associations
- Vocabulary -> Vocabulary: **HierarchicalStructure** (source, type)
- Vocabulary -> Vocabulary: **OntologyMapping** (source, score)
- Gene -> DiseaseOrPhenotypicFeature: **GeneToDiseaseAssociation** (source, type)
- DiseaseOrPhenotypicFeature -> DiseaseOrPhenotypicFeature: **DiseaseToPhenotypicFeatureAssociation** (source, type)
- ChemicalEntity -> DiseaseOrPhenotypicFeature: **ChemicalOrDrugOrTreatmentToDiseaseOrPhenotypicFeatureAssociation** (source, type)
- Gene -> Gene: **GeneToGeneAssociation** (source, type)
- Gene -> Vocabulary: **GeneToExpressionSiteAssociation** (source, type)
- Gene -> Pathway: **GeneToPathwayAssociation** (source, type)
- Gene -> BiologicalProcess | MolecularFunction | CellularComponent: **GeneToGoTermAssociation** (source, type)
- ChemicalEntity -> ChemicalEntity: **ChemicalAffectsGeneAssociation** (source, type)
- ChemicalEntity -> ChemicalEntity: **ChemicalToChemicalAssociation** (source, type)
- SequenceVariant -> Gene: **VariantToGeneAssociation** (source, type, risk allele)
- SequenceVariant -> DiseaseOrPhenotypicFeature: **VariantToDiseaseAssociation** (source, type, risk allele, from_article)
- Vocabulary -> Vocabulary: **Cooccur** (evidence, source, n_article)

## Full-Text Indexes
- **vocabulary_Names**: on Vocabulary.name
- **article_Title**: on Article.title

## Indexed Properties (use for efficient queries)
- Vocabulary: id
- Article: pubmedid, pubdate, n_citation, doi
