import logging
import time
from typing import Any, List, Optional, Union
from google.genai import types

from src.infrastructure.ai.gemini_adapter import GeminiAdapter
from src.infrastructure.ai_client import VisualPart
from src.utils.logger_utils import setup_logger
from src.utils.rate_limiter import CongestionController

logger = setup_logger(__name__)

class GeminiCacheManager:
    """
    Manages the lifecycle of Gemini Context Caches.

    This utility allows for:
    1. Creating a cache from a large context (Market Topography + Visuals).
    2. Retrieving existing caches by name.
    3. Deleting caches manually if needed.
    4. Auto-expiration handling via TTL.
    """

    def __init__(self, adapter: GeminiAdapter, congestion_controller: Optional[CongestionController] = None):
        self._adapter = adapter
        self.client = adapter.raw_client  # underlying genai.Client for cache operations
        self.congestion_controller = congestion_controller
        self.active_cache_resource_name = None

    def create_market_cache(
        self,
        symbol: str,
        interval: str,
        contents: List[Union[str, VisualPart, types.Part]],
        system_instruction: str,
        model: str,
        ttl_minutes: int,
        tools: Optional[List[Any]] = None
    ) -> str:
        """
        Creates a new Context Cache as a 'Truth Bus' for a specific market snapshot.

        Args:
            symbol: Trading pair (e.g., BTCUSDT).
            interval: The macro time interval (e.g., 1h, 4h).
            contents: Observation JSON, VisualParts, or raw types.Part objects.
            system_instruction: The shared instructions to bake into the cache.
            model: The base model (e.g., 'gemini-2.0-flash-001').
            ttl_minutes: Time-to-live in minutes.
            tools: Optional tool definitions to bake into the cache.

        Returns:
            The unique resource name of the created cache.
        """
        start_time = time.perf_counter()

        display_name = f"{symbol}_{interval}_truth_bus_cache"
        logger.info(f"cache init | name={display_name} | ttl={ttl_minutes}m")

        # Convert provider-agnostic VisualParts to Gemini-native types.Part
        gemini_contents = []
        for item in contents:
            if isinstance(item, VisualPart):
                if item.label:
                    gemini_contents.append(types.Part.from_text(text=item.label))
                gemini_contents.append(
                    types.Part.from_bytes(data=item.data, mime_type=item.mime_type))
            else:
                gemini_contents.append(item)

        try:
            # Congestion Control (RPM Pacing)
            if self.congestion_controller:
                self.congestion_controller.pace(agent_name="CacheManager")

            # Create the cache with system instruction and tools baked in
            cache = self.client.caches.create(
                model=model,
                config=types.CreateCachedContentConfig(
                    display_name=f"{symbol}_{display_name}",
                    system_instruction=system_instruction,
                    contents=gemini_contents,
                    tools=tools,  # Tools must be in cache if using cache
                    ttl=f"{ttl_minutes * 60}s",
                ),
            )
            
            elapsed = time.perf_counter() - start_time
            logger.info(f"cache created | name={cache.name} | symbol={symbol} | elapsed={elapsed:.2f}s")
            self.active_cache_resource_name = cache.name
            return cache.name
            
        except Exception as e:
            logger.error(f"cache create failed | symbol={symbol} | error={e}")
            raise  # Fail Fast per user request

    def get_cache(self, cache_resource_name: str) -> Optional[types.CachedContent]:
        """Retrieves cache metadata by resource name."""
        try:
            return self.client.caches.get(name=cache_resource_name)
        except Exception as e:
            logger.warning(f"cache not found | name={cache_resource_name} | error={e}")
            return None

    def delete_cache(self, cache_resource_name: str) -> bool:
        """Manually deletes a cache resource."""
        try:
            self.client.caches.delete(name=cache_resource_name)
            logger.info(f"cache deleted | name={cache_resource_name}")
            return True
        except Exception as e:
            logger.error(f"cache delete failed | name={cache_resource_name} | error={e}")
            return False

    def delete_market_cache(self) -> bool:
        """Stateful cleanup: deletes the last created session cache if active."""
        if not self.active_cache_resource_name:
            logger.debug("no active cache to purge")
            return True
        
        success = self.delete_cache(self.active_cache_resource_name)
        if success:
            self.active_cache_resource_name = None
        return success

    def list_caches(self) -> List[types.CachedContent]:
        """Lists active caches for the current API key."""
        try:
            if self.congestion_controller:
                self.congestion_controller.pace(agent_name="CacheManager_List")
            return list(self.client.caches.list())
        except Exception as e:
            logger.error(f"cache list failed | error={e}")
            return []
