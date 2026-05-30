import pytest
import sys
from shellwise import model
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import urllib.error


class TestEnsureModel:
    def test_model_exists_returns_path(self, mocker):
        mock_path = mocker.patch.object(model, "MODELS_DIR")
        mock_path.__truediv__ = lambda self, x: Path(f"/tmp/{x}")
        mocker.patch("pathlib.Path.exists", return_value=True)
        result = model.ensure_model()
        assert isinstance(result, Path)

    def test_model_downloads_if_missing(self, mocker):
        mock_download = mocker.patch("shellwise.model._download_model")
        mocker.patch("pathlib.Path.exists", return_value=False)
        mocker.patch.object(model, "MODELS_DIR", Path("/tmp"))
        model.ensure_model()
        mock_download.assert_called_once()


class TestDownloadModel:
    def test_download_calls_urlretrieve(self, mocker, tmp_path):
        mock_urlretrieve = mocker.patch("urllib.request.urlretrieve")
        dest = tmp_path / "model.gguf"
        tmp_file = tmp_path / "model.tmp"
        tmp_file.touch()  # Create the tmp file so rename works
        mock_urlretrieve.side_effect = lambda url, path, **kwargs: (path, None)
        model._download_model("http://example.com/model.gguf", dest)
        mock_urlretrieve.assert_called_once()


class TestQueryLlamacpp:
    def test_returns_content(self, mocker):
        mock_llm = MagicMock()
        mock_llm.create_chat_completion.return_value = {
            "choices": [{"message": {"content": "test response"}}]
        }
        mocker.patch("shellwise.model._get_llama", return_value=mock_llm)
        result = model._query_llamacpp(
            [{"role": "user", "content": "test"}],
            Path("/tmp/model.gguf")
        )
        assert result == "test response"

    def test_raises_if_no_llama(self, mocker):
        mocker.patch("shellwise.model._get_llama", return_value=None)
        with pytest.raises(ImportError):
            model._query_llamacpp([], Path("/tmp/model.gguf"))


class TestQueryOllama:
    def test_returns_content(self, mocker):
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"message": {"content": "ollama response"}}'
        mock_urlopen = mocker.patch("urllib.request.urlopen")
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_response)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        result = model._query_ollama([{"role": "user", "content": "test"}])
        assert result == "ollama response"

    def test_raises_on_connection_error(self, mocker):
        mocker.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused")
        )
        with pytest.raises(urllib.error.URLError):
            model._query_ollama([])


class TestQuery:
    def test_tries_llamacpp_first(self, mocker):
        mocker.patch("shellwise.model.ensure_model", return_value=Path("/tmp/model.gguf"))
        mocker.patch("shellwise.model._query_llamacpp", return_value="llama response")
        result = model.query([{"role": "user", "content": "test"}])
        assert result == "llama response"

    def test_falls_back_to_ollama(self, mocker):
        mocker.patch("shellwise.model.ensure_model", side_effect=ImportError)
        mocker.patch("shellwise.model._query_ollama", return_value="ollama response")
        result = model.query([{"role": "user", "content": "test"}])
        assert result == "ollama response"

    def test_raises_connection_error_if_both_fail(self, mocker):
        mocker.patch("shellwise.model.ensure_model", side_effect=ImportError)
        mocker.patch(
            "shellwise.model._query_ollama",
            side_effect=urllib.error.URLError("Connection refused")
        )
        with pytest.raises(ConnectionError):
            model.query([{"role": "user", "content": "test"}])


class TestBackendName:
    def test_returns_ollama_if_not_installed(self, mocker):
        # Need to mock the actual import inside backend_name
        import builtins
        original_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == "llama_cpp":
                raise ImportError("No module named 'llama_cpp'")
            return original_import(name, *args, **kwargs)
        mocker.patch("builtins.__import__", side_effect=mock_import)
        # Clear any cached import
        if "llama_cpp" in sys.modules:
            del sys.modules["llama_cpp"]
        result = model.backend_name()
        assert "ollama" in result
