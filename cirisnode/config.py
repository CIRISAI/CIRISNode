from pydantic_settings import BaseSettings
from pydantic import Extra

class Settings(BaseSettings):
    allowed_blessed_dids: str = ""
    allowed_benchmark_ips: str = ""
    allowed_benchmark_tokens: str = ""
    matrix_logging_enabled: str = ""
    matrix_homeserver_url: str = ""
    matrix_access_token: str = ""
    matrix_room_id: str = ""
    node_api_url: str = ""
    REDIS_URL: str = "redis://localhost:6379/0"  # Default Redis URL
    app_name: str = "CIRISNode"
    max_concurrent_requests: int = 100
    JWT_SECRET: str = "your-jwt-secret"  # Replace with a secure secret
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    VERSION: str = "0.2.0"  # Bumped version for EEE integration
    PUBLIC_KEY: str = ""  # Add public key
    
    # --- EthicsEngine Enterprise Integration Settings ---
    EEE_ENABLED: bool = False  # Feature flag - disabled by default for fork safety
    EEE_BASE_URL: str = "http://localhost:8080"  # EthicsEngine Enterprise API URL
    EEE_TIMEOUT_SECONDS: int = 300  # Timeout for EEE API calls (5 minutes for batch)
    EEE_BATCH_SIZE: int = 50  # Max scenarios per batch request to EEE
    EEE_RETRY_COUNT: int = 3  # Number of retries for failed EEE calls
    EEE_RETRY_DELAY: float = 1.0  # Base delay between retries (seconds)
    HE300_CACHE_TTL: int = 3600  # Cache scenario data for 1 hour (seconds)

    class Config:
        env_file = ".env"
        extra = Extra.allow  # Allow extra env vars (e.g., frontend-only vars in .env)

settings = Settings()

# Add a symmetric key for HS256
HS256_SECRET_KEY = "your-symmetric-key"  # Replace with a securely generated key
