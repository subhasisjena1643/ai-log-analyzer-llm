# src/services/vector_store_flexible.py
import os
import pickle
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
import yaml

from src.services.embedding_service import EmbeddingService

class FlexibleVectorStore:
    def __init__(self, index_name="log_index", config_path="config.yaml"):
        with open(config_path, 'r', encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        self.embedding_service = EmbeddingService(config_path)
        self.index_name = index_name
        self.vector_store_path = config['paths']['vector_store']
        self.index = None
        self.metadata = []
        self.backend = None
        
        # Try different backends in order
        self._init_backend()
        self.load_index()
    
    def _init_backend(self):
        """Try to initialize the best available vector backend"""
        backends = [
            ("faiss", self._init_faiss),
            ("annoy", self._init_annoy),
            ("sklearn", self._init_sklearn),
            ("numpy", self._init_numpy),
        ]

        for backend_name, init_func in backends:
            try:
                init_func()
                self.backend = backend_name   # ← FIX: use the actual backend name
                print(f"[OK] Using {backend_name} as vector store backend")
                return
            except ImportError as e:
                print(f"[INFO] {backend_name} not available: {e}")
                continue
            except Exception as e:
                print(f"[WARNING] Failed to initialize {backend_name}: {e}")
                continue

        raise ImportError("No vector store backend available!")

    
    def _init_faiss(self):
        """Initialize FAISS backend"""
        import faiss
        self.faiss = faiss
        self.dimension = None
    
    def _init_annoy(self):
        """Initialize Annoy backend"""
        from annoy import AnnoyIndex
        self.AnnoyIndex = AnnoyIndex
        self.dimension = None
    
    def _init_sklearn(self):
        """Initialize scikit-learn backend"""
        from sklearn.neighbors import NearestNeighbors
        self.NearestNeighbors = NearestNeighbors
        self.dimension = None
    
    def _init_numpy(self):
        """Initialize numpy fallback backend"""
        self.dimension = None
    
    def load_index(self):
        """Load existing index or create new one"""
        index_path = os.path.join(self.vector_store_path, f"{self.index_name}.pkl")
        
        if os.path.exists(index_path):
            with open(index_path, 'rb') as f:
                data = pickle.load(f)
                self.index = data.get('index')
                self.metadata = data.get('metadata', [])
                self.dimension = data.get('dimension')
                self.backend = data.get('backend', self.backend)
            print(f"[INFO] Loaded existing index with {len(self.metadata)} documents")
        else:
            self.index = None
            self.metadata = []
    
    def save_index(self):
        """Save index and metadata"""
        os.makedirs(self.vector_store_path, exist_ok=True)
        
        save_path = os.path.join(self.vector_store_path, f"{self.index_name}.pkl")
        with open(save_path, 'wb') as f:
            pickle.dump({
                'index': self.index,
                'metadata': self.metadata,
                'dimension': self.dimension,
                'backend': self.backend
            }, f)
    
    def add_documents(self, texts: List[str], metadatas: List[Dict]):
        """Add documents to vector store using the active backend"""
        if not texts:
            return
        
        embeddings = self.embedding_service.encode(texts)
        self.dimension = embeddings.shape[1]
        
        if self.backend == "faiss":
            self._add_faiss(embeddings, metadatas)
        elif self.backend == "annoy":
            self._add_annoy(embeddings, metadatas)
        elif self.backend == "sklearn":
            self._add_sklearn(embeddings, metadatas)
        else:
            self._add_numpy(embeddings, metadatas)
        
        self.metadata.extend(metadatas)
        self.save_index()
    
    def _add_faiss(self, embeddings: np.ndarray, metadatas: List[Dict]):
        """Add to FAISS index"""
        if self.index is None:
            self.index = self.faiss.IndexFlatL2(self.dimension)
        
        self.index.add(embeddings.astype('float32'))
    
    def _add_annoy(self, embeddings: np.ndarray, metadatas: List[Dict]):
        """Add to Annoy index"""
        if self.index is None:
            self.index = self.AnnoyIndex(self.dimension, 'angular')
        
        for i, embedding in enumerate(embeddings):
            self.index.add_item(i, embedding.astype('float32'))
        
        self.index.build(10)  # 10 trees
    
    def _add_sklearn(self, embeddings: np.ndarray, metadatas: List[Dict]):
        """Add to scikit-learn index"""
        if self.index is None:
            self.index = self.NearestNeighbors(metric='cosine', algorithm='brute')
            self.embeddings = embeddings
            self.index.fit(embeddings)
        else:
            # For sklearn, we need to refit
            self.embeddings = np.vstack([self.embeddings, embeddings])
            self.index.fit(self.embeddings)
    
    def _add_numpy(self, embeddings: np.ndarray, metadatas: List[Dict]):
        """Add to numpy fallback"""
        if self.index is None:
            self.index = embeddings
        else:
            self.index = np.vstack([self.index, embeddings])
    
    def search(self, query: str, top_k: int = 5, filter_metadata: Dict = None) -> List[Tuple[float, Dict]]:
        """Search for similar documents"""
        if self.index is None or len(self.metadata) == 0:
            return []
        
        query_embedding = self.embedding_service.encode_single(query)
        
        if self.backend == "faiss":
            return self._search_faiss(query_embedding, top_k, filter_metadata)
        elif self.backend == "annoy":
            return self._search_annoy(query_embedding, top_k, filter_metadata)
        elif self.backend == "sklearn":
            return self._search_sklearn(query_embedding, top_k, filter_metadata)
        else:
            return self._search_numpy(query_embedding, top_k, filter_metadata)
    
    def _search_faiss(self, query_embedding: np.ndarray, top_k: int, filter_metadata: Dict):
        """Search using FAISS"""
        query_embedding = query_embedding.astype('float32').reshape(1, -1)
        distances, indices = self.index.search(
            query_embedding, 
            min(top_k, self.index.ntotal)
        )
        
        return self._format_results(distances[0], indices[0], filter_metadata)
    
    def _search_annoy(self, query_embedding: np.ndarray, top_k: int, filter_metadata: Dict):
        """Search using Annoy"""
        indices, distances = self.index.get_nns_by_vector(
            query_embedding.astype('float32'), 
            top_k, 
            include_distances=True
        )
        
        # Annoy returns squared distances, convert to similarity
        similarities = [1 / (1 + d) for d in distances]
        return self._format_results(similarities, indices, filter_metadata)
    
    def _search_sklearn(self, query_embedding: np.ndarray, top_k: int, filter_metadata: Dict):
        """Search using scikit-learn"""
        distances, indices = self.index.kneighbors(
            query_embedding.reshape(1, -1), 
            n_neighbors=min(top_k, len(self.embeddings))
        )
        
        # Convert cosine distance to similarity
        similarities = [1 - d for d in distances[0]]
        return self._format_results(similarities, indices[0], filter_metadata)
    
    def _search_numpy(self, query_embedding: np.ndarray, top_k: int, filter_metadata: Dict):
        """Search using numpy (brute force)"""
        # Calculate cosine similarity
        query_norm = np.linalg.norm(query_embedding)
        similarities = []
        
        for i, doc_embedding in enumerate(self.index):
            if query_norm == 0 or np.linalg.norm(doc_embedding) == 0:
                sim = 0
            else:
                sim = np.dot(query_embedding, doc_embedding) / (query_norm * np.linalg.norm(doc_embedding))
            similarities.append(sim)
        
        # Get top-k indices
        top_indices = np.argsort(similarities)[-top_k:][::-1]
        top_similarities = [similarities[i] for i in top_indices]
        
        return self._format_results(top_similarities, top_indices, filter_metadata)
    
    def _format_results(self, scores, indices, filter_metadata: Dict) -> List[Tuple[float, Dict]]:
        """Format search results"""
        results = []
        
        for score, idx in zip(scores, indices):
            if idx < len(self.metadata):
                metadata = self.metadata[idx]
                
                # Apply filtering
                if filter_metadata:
                    match = all(
                        metadata.get(key) == value 
                        for key, value in filter_metadata.items()
                    )
                    if not match:
                        continue
                
                results.append((float(score), metadata))
        
        return sorted(results, key=lambda x: x[0], reverse=True)
    
    def size(self):
        """Get number of documents"""
        if self.backend == "faiss":
            return self.index.ntotal if self.index else 0
        elif self.backend == "annoy":
            return self.index.get_n_items() if self.index else 0
        elif self.backend == "sklearn":
            return len(self.embeddings) if hasattr(self, 'embeddings') else 0
        else:
            return len(self.index) if self.index is not None else 0