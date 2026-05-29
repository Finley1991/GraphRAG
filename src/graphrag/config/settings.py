"""Configuration module using Pydantic Settings with YAML file support."""
from pathlib import Path
from typing import Optional
import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class RedisConfig(BaseSettings):
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    scan_queue_name: str = "scan_task"
    parse_queue_name: str = "parse_task"
    index_queue_name: str = "index_task"
    scan_queue_maxsize: int = 500
    parse_queue_maxsize: int = 200
    index_queue_maxsize: int = 1000


class MilvusConfig(BaseSettings):
    host: str = "localhost"
    port: int = 19530
    collection_name: str = "document_chunks"
    index_type: str = "IVF_FLAT"
    metric_type: str = "COSINE"
    nlist: int = 1024


class ElasticsearchConfig(BaseSettings):
    host: str = "localhost"
    port: int = 9200
    index_name: str = "document_chunks"
    ik_analyzer: str = "ik_max_word"
    user: Optional[str] = None
    password: Optional[str] = None


class MinioConfig(BaseSettings):
    endpoint: str = "localhost:9000"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"
    bucket_name: str = "graphrag-images"
    secure: bool = False


class EmbeddingConfig(BaseSettings):
    model_name: str = "jina-embeddings-v5-text-small"
    dimensions: int = 1024
    device: str = "cuda"
    batch_size: int = 32
    max_seq_length: int = 32768
    query_prefix: str = "Query: "
    document_prefix: str = "Document: "
    cache_dir: Optional[str] = None


class ChunkingConfig(BaseSettings):
    section_min_tokens: int = 500
    section_max_tokens: int = 2000
    overlap_tokens: int = 100
    simhash_distance: int = 3
    simhash_bit: int = 64


class PipelineConfig(BaseSettings):
    scan_workers: int = 25
    parse_workers: int = 6
    index_workers: int = 12
    parse_timeout_seconds: int = 120
    docling_batch_size: int = 12
    docling_overlap_pages: int = 2
    context_pages_before: int = 1
    context_pages_after: int = 1


class QueryConfig(BaseSettings):
    doubao_lite_api_key: str = ""
    doubao_pro_api_key: str = ""
    doubao_lite_model: str = "doubao-lite-32k"
    doubao_pro_model: str = "doubao-pro-128k"
    doubao_base_url: str = "https://api.doubao.com/v1"
    temperature_default: float = 0.3
    temperature_max: float = 0.7
    intent_knowledge_base_size: int = 5
    rrf_default_weight: float = 0.5
    es_weight_code: float = 0.8
    milvus_weight_code: float = 0.2
    es_weight_semantic: float = 0.2
    milvus_weight_semantic: float = 0.8
    es_weight_mixed: float = 0.5
    milvus_weight_mixed: float = 0.5


class StorageConfig(BaseSettings):
    pdf_dir: str = str(PROJECT_ROOT / "data" / "pdf")
    html_dir: str = str(PROJECT_ROOT / "data" / "html")
    output_dir: str = str(PROJECT_ROOT / "data" / "output")


class Settings(BaseSettings):
    redis: RedisConfig = Field(default_factory=RedisConfig)
    milvus: MilvusConfig = Field(default_factory=MilvusConfig)
    elasticsearch: ElasticsearchConfig = Field(default_factory=ElasticsearchConfig)
    minio: MinioConfig = Field(default_factory=MinioConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    query: QueryConfig = Field(default_factory=QueryConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)

    model_config = SettingsConfigDict(
        env_prefix="GRAPHRAG_",
        env_nested_delimiter="__",
    )

    @classmethod
    def from_yaml(cls, path: Optional[Path] = None) -> "Settings":
        if path is None:
            path = PROJECT_ROOT / "src" / "graphrag" / "config" / "default.yaml"
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f)
            return cls(**data)
        return cls()


def load_settings() -> Settings:
    return Settings.from_yaml()