import json
import os
from pathlib import Path
import chromadb
from sentence_transformers import SentenceTransformer

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / 'data' / 'knowledge.json'

class KnowledgeService:
    def __init__(self):
        self.client = chromadb.PersistentClient(path=os.getenv('CHROMA_PATH', str(BASE / 'chroma_db')))
        self.collection = self.client.get_or_create_collection('environmental_knowledge')
        self.embedder = SentenceTransformer('all-MiniLM-L6-v2')
        self._seed()

    def _seed(self):
        docs = json.loads(DATA.read_text(encoding='utf-8'))
        existing = self.collection.count()
        if existing >= len(docs):
            return
        ids = [d['id'] for d in docs]
        texts = [self._text(d) for d in docs]
        embeddings = self.embedder.encode(texts).tolist()
        self.collection.upsert(ids=ids, documents=texts, embeddings=embeddings,
                               metadatas=[{k: str(v) for k,v in d.items() if k not in ('id','evidence')} for d in docs])

    def _text(self, d):
        return f"Title: {d['title']}\nSource: {d['source']}\nYear: {d.get('year','')}\nVariables: {', '.join(d.get('variables',[]))}\nMechanism: {d['mechanism']}\nIntervention: {d['intervention']}\nEvidence: {d['evidence']}"

    def search(self, query: str, n: int = 5):
        emb = self.embedder.encode([query]).tolist()
        result = self.collection.query(query_embeddings=emb, n_results=n, include=['documents','metadatas','distances'])
        out=[]
        for i, doc in enumerate(result['documents'][0]):
            meta=result['metadatas'][0][i]
            out.append({'id': result['ids'][0][i], 'distance': result['distances'][0][i], 'text': doc, 'metadata': meta})
        return out
