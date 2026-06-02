import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, mock_open

import pytest

from shellwise import model


# ── ensure_model ─────────────────────────────────────────────────────────────

class TestEnsureModel:
    def test_returns_existing_path(self, mocker, tmp_path):
        existing = tmp_path / "model.gguf"
        existing.touch()
        mocker.patch.object(model, "MODELS_DIR", tmp_path)
        result = model.ensure_model("model.gguf")
        assert result == existing

    def test_downloads_when_missing(self, mocker, tmp_path):
        mocker.patch.object(model, "MODELS_DIR", tmp_path)
        mock_download = mocker.patch("shellwise.model._download_with_resume")
        model.ensure_model("model.gguf")
        mock_download.assert_called_once()
        # first arg is a URL string
        assert mock_download.call_args[0][0].startswith("http")

    def test_tries_each_mirror_on_failure(self, mocker, tmp_path):
        mocker.patch.object(model, "MODELS_DIR", tmp_path)
        mocker.patch.object(
            model, "DEFAULT_MODEL_MIRRORS",
            ["http://mirror1.example.com/x.gguf", "http://mirror2.example.com/x.gguf"],
        )
        mocker.patch.object(
            model, "_download_with_resume",
            side_effect=[RuntimeError("mirror 1 down"), None],
        )
        model.ensure_model("model.gguf")
        assert model._download_with_resume.call_count == 2

    def test_raises_after_all_mirrors_fail(self, mocker, tmp_path):
        mocker.patch.object(model, "MODELS_DIR", tmp_path)
        mocker.patch.object(
            model, "_download_with_resume",
            side_effect=RuntimeError("all down"),
        )
        with pytest.raises(RuntimeError, match="could not download"):
            model.ensure_model("model.gguf")


# ── _query_bundled ───────────────────────────────────────────────────────────

class TestQueryBundled:
    def test_returns_chat_response(self, mocker):
        mocker.patch("shellwise.runner.bundled_binary_available", return_value=True)
        mock_server = MagicMock()
        mock_server.chat.return_value = "bundled response"
        mocker.patch("shellwise.runner.get_server", return_value=mock_server)
        result = model._query_bundled([{"role": "user", "content": "hi"}])
        assert result == "bundled response"
        mock_server.chat.assert_called_once()

    def test_raises_when_binary_missing(self, mocker):
        mocker.patch("shellwise.runner.bundled_binary_available", return_value=False)
        with pytest.raises(FileNotFoundError, match="bundled llama-server not present"):
            model._query_bundled([{"role": "user", "content": "x"}])


# ── _query_llamacpp ─────────────────────────────────────────────────────────

class TestQueryLlamacpp:
    def test_returns_content(self, mocker):
        mock_llm = MagicMock()
        mock_llm.create_chat_completion.return_value = {
            "choices": [{"message": {"content": "llama response"}}]
        }
        mocker.patch.object(model, "_get_llama", return_value=mock_llm)
        result = model._query_llamacpp(
            [{"role": "user", "content": "test"}],
            Path("/tmp/model.gguf"),
        )
        assert result == "llama response"

    def test_raises_if_no_llama(self, mocker):
        mocker.patch.object(model, "_get_llama", return_value=None)
        with pytest.raises(ImportError):
            model._query_llamacpp([], Path("/tmp/model.gguf"))


# ── _query_ollama ────────────────────────────────────────────────────────────

class TestQueryOllama:
    def test_returns_content(self, mocker):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"message": {"content": "ollama response"}}
        ).encode()
        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_response)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        result = model._query_ollama([{"role": "user", "content": "test"}])
        assert result == "ollama response"

    def test_raises_on_connection_error(self, mocker):
        mocker.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        )
        with pytest.raises(urllib.error.URLError):
            model._query_ollama([])


# ── query (priority order) ──────────────────────────────────────────────────

class TestQuery:
    def test_uses_bundled_first(self, mocker):
        mocker.patch.object(model, "_query_bundled", return_value="bundled response")
        mocker.patch.object(model, "_query_llamacpp")
        mocker.patch.object(model, "_query_ollama")
        result = model.query([{"role": "user", "content": "test"}])
        assert result == "bundled response"
        model._query_llamacpp.assert_not_called()
        model._query_ollama.assert_not_called()

    def test_falls_through_bundled_filenotfound(self, mocker):
        mocker.patch.object(model, "_query_bundled", side_effect=FileNotFoundError("no bin"))
        mocker.patch.object(model, "_query_llamacpp", return_value="llama response")
        result = model.query([{"role": "user", "content": "test"}])
        assert result == "llama response"

    def test_falls_through_to_ollama_when_llamacpp_missing(self, mocker):
        mocker.patch.object(model, "_query_bundled", side_effect=FileNotFoundError("no bin"))
        mocker.patch.object(model, "_query_llamacpp", side_effect=ImportError)
        mocker.patch.object(model, "_query_ollama", return_value="ollama response")
        result = model.query([{"role": "user", "content": "test"}])
        assert result == "ollama response"

    def test_raises_connection_error_if_both_fallbacks_fail(self, mocker):
        mocker.patch.object(model, "_query_bundled", side_effect=FileNotFoundError("no bin"))
        mocker.patch.object(model, "_query_llamacpp", side_effect=ImportError)
        mocker.patch.object(
            model, "_query_ollama",
            side_effect=urllib.error.URLError("Connection refused"),
        )
        with pytest.raises(ConnectionError, match="No inference backend available"):
            model.query([{"role": "user", "content": "test"}])

    def test_bundled_runtime_error_falls_through(self, mocker):
        # If bundled binary is present but inference fails for some reason,
        # we should still try the other backends.
        mocker.patch.object(model, "_query_bundled", side_effect=RuntimeError("boom"))
        mocker.patch.object(model, "_query_llamacpp", return_value="llama response")
        result = model.query([{"role": "user", "content": "test"}])
        assert result == "llama response"


# ── backend_name ─────────────────────────────────────────────────────────────

class TestBackendName:
    def test_bundled_when_available(self, mocker):
        mocker.patch.object(model, "_bundled_available", return_value=True)
        assert "bundled llama.cpp" in model.backend_name()

    def test_llamacpp_when_bundled_unavailable(self, mocker):
        mocker.patch.object(model, "_bundled_available", return_value=False)
        # simulate llama_cpp importable
        import sys
        sys.modules["llama_cpp"] = MagicMock()
        try:
            name = model.backend_name()
            assert "llama-cpp-python" in name
        finally:
            del sys.modules["llama_cpp"]

    def test_ollama_as_last_resort(self, mocker):
        mocker.patch.object(model, "_bundled_available", return_value=False)
        import sys
        sys.modules.pop("llama_cpp", None)
        # Patch the import inside backend_name to fail
        import builtins
        orig = builtins.__import__
        def fake_import(name, *a, **kw):
            if name == "llama_cpp":
                raise ImportError
            return orig(name, *a, **kw)
        builtins.__import__ = fake_import
        try:
            name = model.backend_name()
            assert "ollama" in name
        finally:
            builtins.__import__ = orig
