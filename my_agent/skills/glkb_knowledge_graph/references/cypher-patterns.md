# Common Cypher Query Patterns for GLKB

## Vocabulary Search via Full-Text Index
```cypher
CALL db.index.fulltext.queryNodes("vocabulary_Names", "TP53")
YIELD node, score
WITH node as n, score LIMIT 30
WHERE n.connected IS NOT NULL
RETURN n.id, n.name, n.n_citation, n.description
ORDER BY CASE WHEN n.n_citation IS NOT NULL THEN n.n_citation ELSE 0 END DESC
```

## OntologyMapping Expansion
```cypher
MATCH (v:Vocabulary)-[:OntologyMapping]-(v2:Vocabulary)
WHERE v.id IN $ids
RETURN v2.id, v2.name, v2.n_citation
```

## Direct Gene-Disease Association
```cypher
MATCH (g:Gene)-[r:GeneToDiseaseAssociation]->(d:DiseaseOrPhenotypicFeature)
WHERE g.id IN $gene_ids
RETURN g.name, r.type, r.source, d.name, d.id
ORDER BY d.n_citation DESC
LIMIT 50
```

## Gene-Pathway Association
```cypher
MATCH (g:Gene)-[r:GeneToPathwayAssociation]->(p:Pathway)
WHERE g.id IN $gene_ids
RETURN g.name, p.name, p.id, r.source
LIMIT 50
```

## Gene-GO Term Association
```cypher
MATCH (g:Gene)-[r:GeneToGoTermAssociation]->(go)
WHERE g.id IN $gene_ids AND (go:BiologicalProcess OR go:MolecularFunction OR go:CellularComponent)
RETURN g.name, labels(go)[0] as category, go.name, go.id
LIMIT 50
```

## Indirect Connection via Gene-Gene
```cypher
MATCH (g1:Gene)-[:GeneToGeneAssociation]-(g2:Gene)-[:GeneToDiseaseAssociation]->(d:DiseaseOrPhenotypicFeature)
WHERE g1.id IN $gene_ids
RETURN g1.name, g2.name, d.name
LIMIT 50
```

## Cooccurrence Analysis
```cypher
MATCH (v1:Vocabulary)-[c:Cooccur]-(v2:Vocabulary)
WHERE v1.id IN $ids1 AND v2.id IN $ids2
RETURN v1.name, v2.name, c.n_article, c.source
ORDER BY c.n_article DESC
LIMIT 50
```

## Article Search via ContainTerm
```cypher
MATCH (a:Article)-[:ContainTerm]->(v:Vocabulary)
WHERE v.id IN $vocab_ids
RETURN a.pubmedid, a.title, a.n_citation, a.pubdate
ORDER BY a.n_citation DESC
LIMIT 50
```

## Article Full-Text Search
```cypher
CALL db.index.fulltext.queryNodes("article_Title", $keywords)
YIELD node, score
WITH node as a, score LIMIT 100
MATCH (a)-[:PublishedIn]->(j:Journal)
RETURN a.pubmedid, a.title, a.n_citation, a.pubdate, j.impact_factor, score
ORDER BY log(1+5*score) + log(1+a.n_citation) DESC
LIMIT 20
```

## Counting Nodes
```cypher
MATCH (n:Gene) RETURN count(n) as total
```

## Chemical-Disease Association
```cypher
MATCH (c:ChemicalEntity)-[r:ChemicalOrDrugOrTreatmentToDiseaseOrPhenotypicFeatureAssociation]->(d:DiseaseOrPhenotypicFeature)
WHERE c.id IN $chem_ids
RETURN c.name, r.type, d.name
LIMIT 50
```

## Variant-Gene-Disease Path
```cypher
MATCH (sv:SequenceVariant)-[r1:VariantToGeneAssociation]->(g:Gene)-[r2:GeneToDiseaseAssociation]->(d:DiseaseOrPhenotypicFeature)
WHERE sv.rsid = $rsid
RETURN sv.rsid, g.name, r2.type, d.name
LIMIT 50
```
