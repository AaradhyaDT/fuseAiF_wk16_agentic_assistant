import hashlib
import logging
from pathlib import Path

from qdrant_client import QdrantClient, models

logger = logging.getLogger(__name__)

_BATCH_SIZE = 100


def _point_id(doc_id: str) -> int:
    return int.from_bytes(hashlib.sha1(doc_id.encode()).digest()[:8], "big")


class VectorStore:
    """Vector store over Qdrant.

    Embedded-local mode by default (no extra container needed for dev);
    server mode when `url` is provided (docker-compose topology).
    Query hits expose `distance = 1 - cosine_score` so callers keep the
    same relevance math as before.
    """

    def __init__(
        self,
        collection_name: str,
        embedding_fn,
        *,
        path: str | Path | None = None,
        url: str | None = None,
    ) -> None:
        self.collection_name = collection_name
        self.embedding_fn = embedding_fn
        if url:
            self._client = QdrantClient(url=url, timeout=10)
        elif path:
            Path(path).mkdir(parents=True, exist_ok=True)
            self._client = QdrantClient(path=str(path))
        else:
            self._client = QdrantClient(":memory:")

    def _ensure_collection(self) -> None:
        dim = getattr(self.embedding_fn, "dim", None)
        if dim is None:
            dim = len(self.embedding_fn(["dimension-probe"])[0])
        if not self._client.collection_exists(self.collection_name):
            self._client.create_collection(
                self.collection_name,
                vectors_config=models.VectorParams(size=int(dim), distance=models.Distance.COSINE),
            )

    def reset(self) -> None:
        if self._client.collection_exists(self.collection_name):
            self._client.delete_collection(self.collection_name)
        self._ensure_collection()

    def upsert(self, ids: list[str], documents: list[str], metadatas: list[dict]) -> None:
        self._ensure_collection()
        vectors = self.embedding_fn(documents)
        points = []
        for point_id, text, metadata, vector in zip(
            ids, documents, metadatas, vectors, strict=True
        ):
            points.append(
                models.PointStruct(
                    id=_point_id(point_id),
                    vector=vector,
                    payload={**(metadata or {}), "text": text},
                )
            )
        for start in range(0, len(points), _BATCH_SIZE):
            self._client.upsert(self.collection_name, points[start : start + _BATCH_SIZE])

    def count(self) -> int:
        try:
            if not self._client.collection_exists(self.collection_name):
                return 0
            return int(self._client.get_collection(self.collection_name).points_count or 0)
        except Exception as exc:
            logger.warning("vector store count failed: %s", exc)
            return 0

    def query(self, text: str, k: int) -> list[dict]:
        total = self.count()
        if total == 0:
            return []
        vector = self.embedding_fn([text])[0]
        result = self._client.query_points(self.collection_name, query=vector, limit=min(k, total))
        hits = []
        for point in result.points:
            payload = point.payload or {}
            hits.append(
                {
                    "text": payload.get("text", ""),
                    "source": payload.get("source", "unknown"),
                    "distance": 1.0 - float(point.score),
                }
            )
        return hits
