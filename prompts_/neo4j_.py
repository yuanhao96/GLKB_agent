from neo4j import GraphDatabase

GLKB_CONNECTION_URL = "bolt://141.213.137.207:7687"
GLKB_USERNAME = 'neo4j'
GLKB_PASSWORD ='password'

driver = GraphDatabase.driver(GLKB_CONNECTION_URL, auth=(GLKB_USERNAME, GLKB_PASSWORD), max_connection_lifetime=1000)

cypher = '''MATCH(d:Vocabulary{id:'doid:0080636'})-[:GeneToDiseaseAssociation]->(g:Vocabulary)RETURN g.name,g.id LIMIT 100'''

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
