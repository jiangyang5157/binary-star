import logging
import time
from datetime import timedelta
from typing import Dict, Any, List, Optional, Union
from google import genai
from google.genai import types

from src.utils.logger_utils import setup_logger

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
    
    def __init__(self, client: genai.Client):
        self.client = client
        self.active_cache_id = None

    def create_market_cache(
        self, 
        symbol: str,
        interval: str,
        contents: List[Union[str, types.Part]],
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
            contents: Large Observation JSON/Images.
            system_instruction: The shared instructions to bake into the cache.
            model: The base model (e.g., 'gemini-2.0-flash-001').
            ttl_minutes: Time-to-live in minutes.
            tools: Optional tool definitions to bake into the cache.
            
        Returns:
            The unique resource name of the created cache.
        """
        start_time = time.perf_counter()
        
        display_name = f"{symbol}_{interval}_truth_bus_cache"
        logger.info(f"GeminiCacheManager: Initializing Truth Bus cache '{display_name}' (TTL: {ttl_minutes}m)...")
        
        try:
            # Create the cache with system instruction and tools baked in
            cache = self.client.caches.create(
                model=model,
                config=types.CreateCachedContentConfig(
                    display_name=f"{symbol}_{display_name}",
                    system_instruction=system_instruction,
                    contents=contents,
                    tools=tools, # Tools must be in cache if using cache
                    ttl=f"{ttl_minutes * 60}s",
                ),
            )
            
            elapsed = time.perf_counter() - start_time
            logger.info(f"GeminiCache: Successfully created cache {cache.name} for {symbol} in {elapsed:.2f}s. Expires in {ttl_minutes} minutes.")
            self.active_cache_id = cache.name
            return cache.name
            
        except Exception as e:
            logger.error(f"GeminiCache: Failed to create cache for {symbol}: {e}")
            raise  # Fail Fast per user request

    def get_cache(self, cache_resource_name: str) -> Optional[types.CachedContent]:
        """Retrieves cache metadata by resource name."""
        try:
            return self.client.caches.get(name=cache_resource_name)
        except Exception as e:
            logger.warning(f"CacheManager: Could not retrieve cache {cache_resource_name}: {e}")
            return None

    def delete_cache(self, cache_resource_name: str) -> bool:
        """Manually deletes a cache resource."""
        try:
            self.client.caches.delete(name=cache_resource_name)
            logger.info(f"CacheManager: Cache {cache_resource_name} deleted.")
            return True
        except Exception as e:
            logger.error(f"CacheManager: Failed to delete cache {cache_resource_name}: {e}")
            return False

    def delete_market_cache(self) -> bool:
        """Stateful cleanup: deletes the last created session cache if active."""
        if not self.active_cache_id:
            logger.debug("CacheManager: No active market cache to purge.")
            return True
        
        success = self.delete_cache(self.active_cache_id)
        if success:
            self.active_cache_id = None
        return success

    def list_caches(self) -> List[types.CachedContent]:
        """Lists active caches for the current API key."""
        try:
            return list(self.client.caches.list())
        except Exception as e:
            logger.error(f"CacheManager: Failed to list caches: {e}")
            return []
