"""Unit tests for startup validation."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from app.startup import StartupError, _check_vault_path, _check_state_path, _check_qdrant, _check_ollama, validate_startup


# ── _check_vault_path ─────────────────────────────────────────────────────────

class TestCheckVaultPath:
    def test_valid_directory_passes(self, tmp_path):
        with patch("app.startup.settings") as s:
            s.vault_path = str(tmp_path)
            _check_vault_path()  # no exception

    def test_nonexistent_path_raises(self, tmp_path):
        with patch("app.startup.settings") as s:
            s.vault_path = str(tmp_path / "does_not_exist")
            with pytest.raises(StartupError, match="does not exist"):
                _check_vault_path()

    def test_file_instead_of_directory_raises(self, tmp_path):
        f = tmp_path / "file.md"
        f.write_text("hello")
        with patch("app.startup.settings") as s:
            s.vault_path = str(f)
            with pytest.raises(StartupError, match="not a directory"):
                _check_vault_path()


# ── _check_state_path ─────────────────────────────────────────────────────────

class TestCheckStatePath:
    def test_existing_writable_parent_passes(self, tmp_path):
        with patch("app.startup.settings") as s:
            s.index_state_path = str(tmp_path / "state.json")
            _check_state_path()  # no exception

    def test_creates_missing_parent(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "state.json"
        with patch("app.startup.settings") as s:
            s.index_state_path = str(deep)
            _check_state_path()
            assert deep.parent.exists()

    def test_error_message_mentions_fix(self, tmp_path):
        with patch("app.startup.settings") as s:
            s.index_state_path = str(tmp_path / "state.json")
            # Simulate an OSError during mkdir
            with patch("pathlib.Path.mkdir", side_effect=OSError("permission denied")):
                with patch("pathlib.Path.exists", return_value=False):
                    with pytest.raises(StartupError, match="Fix"):
                        _check_state_path()


# ── _check_qdrant ─────────────────────────────────────────────────────────────

class TestCheckQdrant:
    async def test_healthy_response_passes(self):
        mock_response = AsyncMock()
        mock_response.status_code = 200

        with patch("app.startup.settings") as s, \
             patch("httpx.AsyncClient") as mock_client_cls:
            s.qdrant_url = "http://qdrant:6333"
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            await _check_qdrant()  # no exception

    async def test_non_200_raises(self):
        mock_response = AsyncMock()
        mock_response.status_code = 503

        with patch("app.startup.settings") as s, \
             patch("httpx.AsyncClient") as mock_client_cls:
            s.qdrant_url = "http://qdrant:6333"
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with pytest.raises(StartupError, match="HTTP 503"):
                await _check_qdrant()

    async def test_connect_error_raises(self):
        with patch("app.startup.settings") as s, \
             patch("httpx.AsyncClient") as mock_client_cls:
            s.qdrant_url = "http://qdrant:6333"
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client_cls.return_value = mock_client

            with pytest.raises(StartupError, match="Cannot connect to Qdrant"):
                await _check_qdrant()

    async def test_timeout_raises(self):
        with patch("app.startup.settings") as s, \
             patch("httpx.AsyncClient") as mock_client_cls:
            s.qdrant_url = "http://qdrant:6333"
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client_cls.return_value = mock_client

            with pytest.raises(StartupError, match="timed out"):
                await _check_qdrant()

    async def test_error_message_contains_fix(self):
        with patch("app.startup.settings") as s, \
             patch("httpx.AsyncClient") as mock_client_cls:
            s.qdrant_url = "http://qdrant:6333"
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client_cls.return_value = mock_client

            with pytest.raises(StartupError, match="Fix"):
                await _check_qdrant()


# ── _check_ollama ─────────────────────────────────────────────────────────────

class TestCheckOllama:
    def _make_client(self, status_code: int, body: dict):
        from unittest.mock import MagicMock
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.json = MagicMock(return_value=body)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        return mock_client

    async def test_healthy_with_models_passes(self):
        with patch("app.startup.settings") as s, \
             patch("httpx.AsyncClient") as mock_client_cls:
            s.ollama_base_url = "http://ollama:11434"
            s.ollama_embed_model = "nomic-embed-text"
            s.ollama_chat_model = "qwen2.5"
            mock_client_cls.return_value = self._make_client(200, {
                "models": [
                    {"name": "nomic-embed-text"},
                    {"name": "qwen2.5"},
                ]
            })
            await _check_ollama()  # no exception

    async def test_missing_model_warns_not_raises(self, caplog):
        import logging
        with patch("app.startup.settings") as s, \
             patch("httpx.AsyncClient") as mock_client_cls:
            s.ollama_base_url = "http://ollama:11434"
            s.ollama_embed_model = "nomic-embed-text"
            s.ollama_chat_model = "qwen2.5"
            mock_client_cls.return_value = self._make_client(200, {"models": []})

            with caplog.at_level(logging.WARNING, logger="app.startup"):
                await _check_ollama()  # must not raise

            assert any("not found" in r.message for r in caplog.records)

    async def test_connect_error_raises(self):
        with patch("app.startup.settings") as s, \
             patch("httpx.AsyncClient") as mock_client_cls:
            s.ollama_base_url = "http://ollama:11434"
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client_cls.return_value = mock_client

            with pytest.raises(StartupError, match="Cannot connect to Ollama"):
                await _check_ollama()

    async def test_model_prefix_match_accepted(self):
        # Ollama sometimes returns "qwen2.5:latest" for model "qwen2.5"
        with patch("app.startup.settings") as s, \
             patch("httpx.AsyncClient") as mock_client_cls:
            s.ollama_base_url = "http://ollama:11434"
            s.ollama_embed_model = "nomic-embed-text"
            s.ollama_chat_model = "qwen2.5"
            mock_client_cls.return_value = self._make_client(200, {
                "models": [
                    {"name": "nomic-embed-text:latest"},
                    {"name": "qwen2.5:7b-instruct"},
                ]
            })
            await _check_ollama()  # no exception, prefix match passes


# ── validate_startup (integration of all checks) ──────────────────────────────

class TestValidateStartup:
    async def test_all_pass(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()

        def mock_check_vault():
            pass

        def mock_check_state():
            pass

        async def mock_check_qdrant():
            pass

        async def mock_check_ollama():
            pass

        with patch("app.startup._check_vault_path", mock_check_vault), \
             patch("app.startup._check_state_path", mock_check_state), \
             patch("app.startup._check_qdrant", mock_check_qdrant), \
             patch("app.startup._check_ollama", mock_check_ollama):
            await validate_startup()  # no exception

    async def test_vault_failure_propagates(self):
        with patch("app.startup._check_vault_path", side_effect=StartupError("vault missing")):
            with pytest.raises(StartupError, match="vault missing"):
                await validate_startup()

    async def test_qdrant_failure_propagates(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()

        with patch("app.startup._check_vault_path"), \
             patch("app.startup._check_state_path"), \
             patch("app.startup._check_qdrant", AsyncMock(side_effect=StartupError("qdrant down"))), \
             patch("app.startup._check_ollama", AsyncMock()):
            with pytest.raises(StartupError, match="qdrant down"):
                await validate_startup()
