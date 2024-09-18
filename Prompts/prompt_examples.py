examples= [
    {
        "question": "What is the articles with PubMed ID 23?",
        "query": "MATCH (a:Article) WHERE a.pubmedid = '23' RETURN a.title, a.authors, a.pubdate",
    },
    {
        "question": "How many articles have citation > 50? Return their title and authors",
        "query": "MATCH (a:Article) WHERE a.n_citation > 50  RETURN a.title, a.authors",
    },
    {
        "question": "Which gene is named TP53?",
        "query": """CALL db.index.fulltext.queryNodes("vocabulary_Names", "'TP53'") YIELD node, score WITH node as n, score LIMIT 7 RETURN n.id, n.name, n.description ORDER BY CASE WHEN n.n_citation IS NOT NULL THEN n.n_citation ELSE 0 END DESC""",
    },
    {
        "question": "get the id of type 2 diabetes?",
        "query": """CALL db.index.fulltext.queryNodes("vocabulary_Names", "'type 2 diabetes'") YIELD node, score WITH node as n, score LIMIT 7 RETURN n.id, n.name, n.description ORDER BY CASE WHEN n.n_citation IS NOT NULL THEN n.n_citation ELSE 0 END DESC""",
    },
    {
        "question": "define breast cancer",
        "query": """CALL db.index.fulltext.queryNodes("vocabulary_Names", "'breast cancer'") YIELD node, score WITH node as n, score LIMIT 7 RETURN n.id, n.name, n.description ORDER BY CASE WHEN n.n_citation IS NOT NULL THEN n.n_citation ELSE 0 END DESC""",
    },
    {
        "question": "What are the articles published in a specific journal?",
        "query": "MATCH (a:Article)-[:PublishedIn]-(j:Journal) WHERE j.title = 'Journal Name' RETURN a.title",
    },
    {
        "question": "How many authors collaborated on a particular article?",
        "query": "MATCH (a:Article) WHERE a.pubmedid = 'PubMed ID' RETURN size(a.authors)",
    },
    {
        "question": "Which article is with a specific title or abstract?",
        "query": """CALL db.index.fulltext.queryNodes("article_Title", "'Title or Abstract'") YIELD node, score WITH node as n, score LIMIT 10 RETURN n.pubmedid, n.title, n.n_citation""",
    },
    {
        "question": "What are the articles that cite a specific article?", 
        "query": "MATCH (a:Article {{pubmedid: 'PubMed ID'}})<-[:Cite]-(c:Article) RETURN c.title",
    },
    {
        "question": "Based on the curated databases, what diseases are related to a specific gene?",
        "query": "MATCH (v:Vocabulary {{id: 'hgnc:HGNC_ID'}})-[:GeneToDiseaseAssociation]->(d:Vocabulary) RETURN d.name, d.id, d.n_citation",
    },
    {
        "question": "What are the top journals by the number of articles published?",
        "query": "MATCH (j:Journal)-[:PublishedIn]-(a:Article) RETURN j.title, count(a) AS num_articles ORDER BY num_articles DESC LIMIT 10",
    },
    {
        "question": "What are the top 10 cited articles by a particular journal", 
        "query": "MATCH (j:Journal)-[:PublishedIn]-(a:Article) WHERE j.title='The Plant Journal' WITH a ORDER BY a.n_citation DESC RETURN a.title LIMIT 10",
    },
    {
        "question": "How many articles were published in a specific year, e.g 2020?",
        "query": "MATCH (a:Article) WHERE a.pubdate=2020 RETURN COUNT(a)",
    },
    {
        "question": "What are the articles published after a specific year?",
        "query": "MATCH (a:Article) WHERE a.pubdate > year RETURN a.title",
    },
    {
        "question": "What is the GO term with ID 0035267?",
        "query": "MATCH (v:Vocabulary {{id: 'go:0035267'}}) RETURN v.name",
    },
    {
        "question": "What are the aliases of the gene with HGNC id 11997?",
        "query": "MATCH (v:Vocabulary {{id: 'hgnc:11997'}}) RETURN v.synonyms",
    },
    {
        "question": "What is the disease with DOID 0050606?",
        "query": "MATCH (v:Vocabulary {{id: 'doid:0050606'}}) RETURN v.name",
    },
    {
        "question": "What are the cross references of the MESH term D007644 in other ontologies?",
        "query": "MATCH (v:Vocabulary {{id: 'mesh:D007644'}})-[:OntologyMapping]->(o:Vocabulary) RETURN o.name, o.id",
    },
    {
        "question": "What is the most cited article of a specific biomedical concept?",
        "query": "MATCH (v:Vocabulary {{id: 'Concept ID'}})-[:ContainTerm]-(a:Article) RETURN a.title ORDER BY a.n_citation DESC LIMIT 1",
    },
    {
        "question": "Which genetic variant affects a specific gene?",
        "query": "MATCH (:Vocabulary {{id: 'Concept ID'}})-[:VariantToGeneAssociation]-(v:Vocabulary) RETURN v.id, v.name",
    },
    {
        "question": "What is the reference and alternative alleles of the genetic variant with RSID rs35850753?",
        "query": "MATCH (v:Vocabulary {{id: 'rs35850753'}}) RETURN v.ref, v.alt",
    },
    {
        "question": "What are the subclasses of the disease mondo:0018800?",
        "query": "MATCH (v:Vocabulary)-[:HierarchicalStructure]->(d:Vocabulary {{id: 'mondo:0018800'}}) RETURN v.name, v.id",
    },
]