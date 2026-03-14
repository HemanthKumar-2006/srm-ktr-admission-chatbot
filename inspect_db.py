import chromadb
from pathlib import Path

client = chromadb.PersistentClient(path="vector_db")
collections = client.list_collections()
print(f"Collections: {collections}")

for coll in collections:
    c = client.get_collection(coll.name)
    print(f"Collection: {coll.name}, Count: {c.count()}")
