# Neo4j Browser Visualization Queries

Use these queries in Neo4j Browser at `http://localhost:7474/browser` to inspect the CodeMemory graph.

## Connect

- URI: `bolt://localhost:7687`
- Username: `neo4j`
- Password: your configured Neo4j password

After each query, switch the result panel to **Graph** view.

## Quick Visual Checks

```cypher
MATCH (n)
RETURN n
LIMIT 25;
```

```cypher
MATCH p=()-[r]->()
RETURN p
LIMIT 50;
```

## Focused Structural Views

```cypher
MATCH p=(f:File)-[:DEFINES]->(e)
RETURN p
LIMIT 100;
```

```cypher
MATCH p=(f:File)-[:IMPORTS]->(g:File)
RETURN p
LIMIT 100;
```

## Broader Sample (Safer Than Full-Graph Render)

```cypher
MATCH p=()-[r]->()
RETURN p
LIMIT 500;
```

```cypher
MATCH (f:File)
WITH f ORDER BY rand() LIMIT 100
MATCH p=(f)-[r*1..2]-()
RETURN p
LIMIT 1000;
```

## Graph Size / Health Checks (Table-Friendly)

```cypher
MATCH (n)
RETURN count(n) AS nodes;
```

```cypher
MATCH ()-[r]->()
RETURN count(r) AS rels;
```

```cypher
MATCH (n)
RETURN labels(n), count(*)
ORDER BY count(*) DESC;
```

```cypher
MATCH ()-[r]->()
RETURN type(r), count(*)
ORDER BY count(*) DESC;
```

## Notes

- Avoid trying to render every node and edge at once on larger graphs; Browser can become slow or unresponsive.
- Use `LIMIT` and label-scoped patterns (`File`, `Function`, `Class`, `Chunk`) to keep exploration responsive.
