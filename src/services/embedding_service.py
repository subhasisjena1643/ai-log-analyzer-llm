# src/services/embedding_service.py

import numpy as np
import pickle
import os
from typing import List, Dict
import yaml
import huggingface_hub
from huggingface_hub import hf_hub_download
from sentence_transformers import SentenceTransformer

# Compatibility patch for newer huggingface_hub (DO NOT REMOVE)
if not hasattr(huggingface_hub, "cached_download"):
    huggingface_hub.cached_download = hf_hub_download


class EmbeddingService:
    def __init__(self, config_path="config.yaml"):
        with open(config_path, 'r', encoding="utf-8") as f:
            config = yaml.safe_load(f)

        self.model_name = config['embedding']['model_name']
        self.model = SentenceTransformer(self.model_name)
        self.vector_store_path = config['paths']['vector_store']

        os.makedirs(self.vector_store_path, exist_ok=True)

    def encode(self, texts: List[str]) -> np.ndarray:
        """Convert list of texts to embeddings"""
        return self.model.encode(texts, show_progress_bar=False)

    def encode_single(self, text: str) -> np.ndarray:
        """Convert single text to embedding"""
        return self.encode([text])[0]

    def save_embeddings(self, embeddings: np.ndarray, metadata: List[Dict], name: str):
        """Save embeddings and metadata"""
        save_path = os.path.join(self.vector_store_path, f"{name}.pkl")
        with open(save_path, 'wb') as f:
            pickle.dump({'embeddings': embeddings, 'metadata': metadata}, f)

    def load_embeddings(self, name: str):
        """Load embeddings and metadata"""
        load_path = os.path.join(self.vector_store_path, f"{name}.pkl")
        if os.path.exists(load_path):
            with open(load_path, 'rb') as f:
                return pickle.load(f)
        return None
