"""Tests for configuration module."""
import pytest
from graphrag.config.settings import Settings, load_settings


def test_load_settings_from_yaml():
    settings = load_settings()
    assert settings.redis.scan_queue_name == "scan_task"
    assert settings.redis.parse_queue_name == "parse_task"
    assert settings.redis.index_queue_name == "index_task"
    assert settings.milvus.host == "localhost"
    assert settings.milvus.port == 19530
    assert settings.elasticsearch.host == "localhost"
    assert settings.elasticsearch.port == 9200
    assert settings.minio.endpoint == "localhost:9000"
    assert settings.embedding.model_name == "jina-embeddings-v5-text-small"
    assert settings.embedding.dimensions == 1024
    assert settings.chunking.section_min_tokens == 500
    assert settings.chunking.section_max_tokens == 2000
    assert settings.chunking.overlap_tokens == 100
    assert settings.pipeline.scan_workers == 25
    assert settings.pipeline.parse_workers == 6
    assert settings.pipeline.index_workers == 12
    assert settings.query.doubao_lite_model == "doubao-lite-32k"
    assert settings.query.doubao_pro_model == "doubao-pro-128k"
    assert settings.query.rrf_default_weight == 0.5