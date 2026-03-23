"""Tests for sylvan.server.startup — warmup and signal handling."""

from __future__ import annotations

import signal
from unittest.mock import patch


class TestWarmUp:
    """Tests for warm_up()."""

    def test_warm_up_completes(self):
        """warm_up() finishes without errors."""
        from sylvan.server.startup import warm_up

        warm_up()

    def test_warm_up_handles_embedding_failure(self):
        """warm_up() continues when embedding loading fails."""
        from sylvan.server.startup import warm_up

        with patch(
            "sylvan.search.embeddings.get_embedding_provider",
            side_effect=ImportError("no embedding provider"),
        ):
            # Should not raise — the except block handles it
            warm_up()

    def test_warm_up_skips_unavailable_provider(self):
        """warm_up() skips embedding when provider.available() is False."""
        from unittest.mock import MagicMock

        from sylvan.server.startup import warm_up

        mock_provider = MagicMock()
        mock_provider.available.return_value = False

        with patch("sylvan.search.embeddings.get_embedding_provider", return_value=mock_provider):
            warm_up()
            mock_provider.embed_one.assert_not_called()


class TestRegisterSignalHandlers:
    """Tests for _register_signal_handlers()."""

    def test_registers_sigterm_handler(self):
        """_register_signal_handlers installs a SIGTERM handler."""
        from sylvan.server.startup import _register_signal_handlers

        old_handler = signal.getsignal(signal.SIGTERM)
        try:
            _register_signal_handlers()
            new_handler = signal.getsignal(signal.SIGTERM)
            # Should have replaced the default handler
            assert new_handler is not signal.SIG_DFL
            assert callable(new_handler)
        finally:
            signal.signal(signal.SIGTERM, old_handler)

    def test_registers_sigint_handler(self):
        """_register_signal_handlers installs a SIGINT handler."""
        from sylvan.server.startup import _register_signal_handlers

        old_handler = signal.getsignal(signal.SIGINT)
        try:
            _register_signal_handlers()
            new_handler = signal.getsignal(signal.SIGINT)
            assert callable(new_handler)
        finally:
            signal.signal(signal.SIGINT, old_handler)
