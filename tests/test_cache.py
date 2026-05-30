import pytest
import time
import json
from pathlib import Path
from unittest.mock import patch
from shellwise import cache


class TestNormalizeQuery:
    def test_lowercases(self):
        assert cache._normalize_query("LIST Files") == "list files"

    def test_collapses_spaces(self):
        assert cache._normalize_query("list   files") == "list files"

    def test_trims(self):
        assert cache._normalize_query("  list files  ") == "list files"


class TestIsSensitive:
    def test_password(self):
        assert cache._is_sensitive("my password is secret") is True

    def test_api_key(self):
        assert cache._is_sensitive("api_key=abc123") is True

    def test_token(self):
        assert cache._is_sensitive("bearer token xyz") is True

    def test_safe_query(self):
        assert cache._is_sensitive("list all files") is False


class TestSanitizePath:
    def test_replaces_home(self):
        home = str(Path.home())
        result = cache._sanitize_path(f"{home}/projects")
        assert result == "~/projects"

    def test_no_home(self):
        result = cache._sanitize_path("/tmp/test")
        assert result == "/tmp/test"


class TestBuildKey:
    def test_same_input_same_key(self):
        k1 = cache._build_key("/tmp", "list files")
        k2 = cache._build_key("/tmp", "list files")
        assert k1 == k2

    def test_different_cwd_different_key(self):
        k1 = cache._build_key("/tmp", "list files")
        k2 = cache._build_key("/var", "list files")
        assert k1 != k2

    def test_case_insensitive(self):
        k1 = cache._build_key("/tmp", "LIST FILES")
        k2 = cache._build_key("/tmp", "list files")
        assert k1 == k2


class TestCacheGetSet:
    def test_set_and_get(self, tmp_path):
        cache_file = tmp_path / "cache.jsonl"
        with patch.object(cache, "CACHE_FILE", cache_file):
            with patch.object(cache, "CACHE_DIR", tmp_path):
                cache.cache_set("/tmp", "list files", {"commands": [{"cmd": "ls"}]})
                result = cache.cache_get("/tmp", "list files")
                assert result is not None
                assert result["commands"][0]["cmd"] == "ls"

    def test_get_miss(self, tmp_path):
        cache_file = tmp_path / "cache.jsonl"
        with patch.object(cache, "CACHE_FILE", cache_file):
            with patch.object(cache, "CACHE_DIR", tmp_path):
                result = cache.cache_get("/tmp", "nonexistent query")
                assert result is None

    def test_skip_sensitive(self, tmp_path):
        cache_file = tmp_path / "cache.jsonl"
        with patch.object(cache, "CACHE_FILE", cache_file):
            with patch.object(cache, "CACHE_DIR", tmp_path):
                cache.cache_set("/tmp", "my password is secret", {"commands": []})
                result = cache.cache_get("/tmp", "my password is secret")
                assert result is None

    def test_expiry(self, tmp_path):
        cache_file = tmp_path / "cache.jsonl"
        with patch.object(cache, "CACHE_FILE", cache_file):
            with patch.object(cache, "CACHE_DIR", tmp_path):
                with patch.object(cache, "READ_TTL", 0):
                    cache.cache_set("/tmp", "list files", {"commands": [{"cmd": "ls"}]})
                    time.sleep(0.1)
                    result = cache.cache_get("/tmp", "list files")
                    assert result is None
