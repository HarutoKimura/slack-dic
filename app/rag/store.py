"""Chroma vector database interface."""

from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.rag.embed import EmbeddingClient
from app.settings import settings


class VectorStore:
    """Chroma vector database wrapper."""

    def __init__(
        self,
        collection_name: str = "slack_messages",
        persist_directory: str | None = None,
    ):
        """
        Initialize the vector store.

        Args:
            collection_name: Name of the collection
            persist_directory: Directory to persist the database
        """
        self.persist_directory = persist_directory or settings.chroma_persist_directory
        self.embedding_client = EmbeddingClient()

        # Initialize Chroma client
        self.client = chromadb.PersistentClient(
            path=self.persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name=collection_name, metadata={"hnsw:space": "cosine"}
        )

    def upsert(self, docs: list[dict[str, Any]]) -> None:
        """
        Upsert documents into the vector store.

        Args:
            docs: List of documents with structure:
                {
                    "id": "unique-id",
                    "text": "document text",
                    "metadata": {...}
                }
        """
        if not docs:
            return

        ids = [doc["id"] for doc in docs]
        texts = [doc["text"] for doc in docs]
        metadatas = [doc.get("metadata", {}) for doc in docs]

        # Generate embeddings if not present
        if "embedding" in docs[0]:
            embeddings = [doc["embedding"] for doc in docs]
        else:
            print("Generating embeddings for upsert...")
            embeddings = self.embedding_client.embed_texts(texts)

        # Upsert to Chroma
        self.collection.upsert(
            ids=ids, documents=texts, embeddings=embeddings, metadatas=metadatas
        )

        print(f"Upserted {len(docs)} documents to vector store")

    def query(
        self, query_text: str, top_k: int = 5
    ) -> list[dict[str, Any]]:
        """
        Query the vector store.

        Args:
            query_text: Query text
            top_k: Number of results to return

        Returns:
            List of results with structure:
                {
                    "id": "doc-id",
                    "text": "document text",
                    "metadata": {...},
                    "distance": 0.123
                }
        """
        # Generate query embedding
        query_embedding = self.embedding_client.embed_text(query_text)

        # Query Chroma
        results = self.collection.query(
            query_embeddings=[query_embedding], n_results=top_k
        )

        # Format results
        formatted_results = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                result = {
                    "id": doc_id,
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i] if results["distances"] else 0.0,
                }
                formatted_results.append(result)

        return formatted_results

    def count(self) -> int:
        """Get the number of documents in the collection."""
        return self.collection.count()

    def delete_all(self) -> None:
        """Delete all documents from the collection."""
        # Delete the collection and recreate it
        self.client.delete_collection(self.collection.name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection.name, metadata={"hnsw:space": "cosine"}
        )
        print("Deleted all documents from vector store")
