from neo4j import GraphDatabase

GLKB_CONNECTION_URL = "bolt://141.213.137.207:7687"
GLKB_USERNAME = 'neo4j'
GLKB_PASSWORD ='password'

driver = GraphDatabase.driver(GLKB_CONNECTION_URL, auth=(GLKB_USERNAME, GLKB_PASSWORD), max_connection_lifetime=1000)

cypher = '''CALL db.index.fulltext.queryNodes("article_Title", "'CRISPR'") YIELD node, score WITH node as n, score LIMIT 10 RETURN n, ID(n), n.id, n.title, n.n_citation, n.score'''

# with driver.session() as session:
#     res = session.run(cypher).value().copy()
#     print(res)

def run_cypher(command: str):
    with driver.session() as session:
        result = session.run(command)
        res = [record.data() for record in result]
        return res

if __name__ == '__main__':
    print(run_cypher(cypher))
