import pytest
from unittest.mock import MagicMock, patch
from tests.mock_factory import MockDataFactory

@pytest.fixture
def mock_config():
    return MockDataFactory.create_mock_config()

@pytest.fixture
def mock_orchestrator_infrastructure(mock_config):
    """Global patcher for external infrastructure dependencies."""
    with patch('google.genai.Client'), \
         patch('src.infrastructure.binance.client.BinanceFuturesClient'), \
         patch('src.analyzer.chart_generator.ChartGenerator'), \
         patch('src.infrastructure.gemini.cache_manager.GeminiCacheManager'), \
         patch('src.agent.binary_star_orchestrator.load_config', return_value=mock_config), \
         patch('src.utils.pipeline_utils.read_prompt_template', return_value="Mock Instruction"):
        yield
