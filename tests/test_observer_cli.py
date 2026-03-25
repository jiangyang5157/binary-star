import unittest
import os
from unittest.mock import patch, MagicMock
from observer import ObserverCLI, ObservationArgs, ObservationPersistor
from src.utils.agent_utils import load_config
from dotenv import load_dotenv

class TestObserverCLI(unittest.TestCase):
    def setUp(self):
        load_dotenv()
        self.config = load_config()
        self.symbol = "BTCUSDT"
        self.data_root = "data/tests"

    def test_argument_defaults(self):
        """Verify that default values are correctly handled in the logic."""
        # This tests the logic inside our Orchestrator if we manually pass args
        args = ObservationArgs(symbol=self.symbol, timestamp_raw=None, data_root="data")
        self.assertEqual(args.data_root, "data")
        self.assertIsNone(args.timestamp_raw)

    def test_timestamp_parsing_logic(self):
        """Verify that ISO-8601 strings are correctly converted."""
        ts_str = "2026-03-24T10:00:00"
        args = ObservationArgs(symbol=self.symbol, timestamp_raw=ts_str, data_root=self.data_root)
        cli = ObserverCLI(args)
        
        parsed_ts = cli._parse_target_time()
        self.assertIsNotNone(parsed_ts)
        self.assertEqual(parsed_ts.year, 2026)
        self.assertEqual(parsed_ts.month, 3)
        self.assertEqual(parsed_ts.day, 24)

    def test_persistence_logic(self):
        """Verify that the persistor correctly saves results and creates paths."""
        mock_context = {
            "symbol": "BTCUSDT",
            "timestamp": "2026-03-25T15:30:00Z",
            "data": "test"
        }
        
        # Test saving
        saved_path = ObservationPersistor.save_result(mock_context, self.symbol, self.data_root)
        self.assertTrue(os.path.exists(saved_path))
        self.assertIn("observations", saved_path)
        self.assertIn(self.symbol, saved_path)
        
        # Cleanup
        if os.path.exists(saved_path):
            os.remove(saved_path)

    @patch('src.agent.observer_agent.ObserverAgent.observe')
    def test_cli_run_orchestration(self, mock_observe):
        """Verify the high-level run sequence with mocked agent."""
        mock_observe.return_value = {
            "symbol": "BTCUSDT",
            "timestamp": "2026-03-25T15:30:00Z",
            "observation_specs": {"macro": {"interval": "1h", "limit": 100}}
        }
        
        args = ObservationArgs(symbol=self.symbol, timestamp_raw=None, data_root=self.data_root)
        cli = ObserverCLI(args)
        
        # Run the pipeline (mocking the agent so we don't hit real APIs here)
        cli.run()
        
        # Verify persistence was called implicitly
        expected_file = f"BTCUSDT_observations_20260325_153000.json"
        expected_path = os.path.join(self.data_root, "observations", expected_file)
        self.assertTrue(os.path.exists(expected_path))
        
        # Cleanup
        if os.path.exists(expected_path):
            os.remove(expected_path)

    def test_live_pipeline_integration(self):
        """
        Optional: Full end-to-end integration test with real APIs.
        Only runs if GEMINI_API_KEY is available.
        """
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            self.skipTest("GEMINI_API_KEY not found in environment")

        args = ObservationArgs(symbol=self.symbol, timestamp_raw=None, data_root=self.data_root)
        cli = ObserverCLI(args)
        
        # Execute live pipeline
        cli.run()
        
        # Check if observations directory has files
        obs_dir = os.path.join(self.data_root, "observations")
        self.assertTrue(os.path.exists(obs_dir))
        files = os.listdir(obs_dir)
        self.assertTrue(any(f.startswith(self.symbol) for f in files))

if __name__ == "__main__":
    unittest.main()
