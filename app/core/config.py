from pydantic import PostgresDsn, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDERS = {"changethis", "change_me", "change-me", "change me"}
_PLACEHOLDER = "changethis"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "InfraScope"
    ENVIRONMENT: str = "development"

    SECRET_KEY: str = _PLACEHOLDER

    # Comma-separated Fernet keys for encrypting secrets at rest (e.g. switch
    # SSH passwords). First key encrypts; all are tried for decryption, so a
    # new key can be prepended to rotate without breaking existing rows.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Leave empty to disable (values are stored as plaintext, as before).
    CREDENTIALS_ENCRYPTION_KEYS: str = ""

    @staticmethod
    def _is_weak_bootstrap_password(value: str) -> bool:
        normalized = (value or "").strip()
        normalized_lower = normalized.lower()
        if not normalized or normalized_lower in _PLACEHOLDERS:
            return True
        if len(normalized) < 12:
            return True
        if normalized.isdigit() or normalized.isalpha():
            return True
        return False

    @model_validator(mode="after")
    def validate_secret_key(self) -> "Settings":
        if self.ENVIRONMENT == "production" and self.SECRET_KEY.strip().lower() in _PLACEHOLDERS:
            raise ValueError(
                "SECRET_KEY must be set to a secure value in production. "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        if self.ENVIRONMENT == "production" and self._is_weak_bootstrap_password(self.FIRST_SUPERUSER_PASSWORD):
            raise ValueError("FIRST_SUPERUSER_PASSWORD must be explicitly set to a strong value in production.")
        internal_services_enabled = any(
            (
                self.POLLING_SERVICE_ENABLED,
                self.DISCOVERY_SERVICE_ENABLED,
                self.NETWORK_CONTROL_SERVICE_ENABLED,
            )
        )
        if self.ENVIRONMENT == "production" and internal_services_enabled and not self.INTERNAL_SERVICE_TOKEN.strip():
            raise ValueError("INTERNAL_SERVICE_TOKEN must be set in production when internal services are enabled.")
        return self

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30  # 30 days
    AUTH_COOKIE_SECURE: bool = False

    FIRST_SUPERUSER_EMAIL: str = "admin@infrascope.dev"
    FIRST_SUPERUSER_PASSWORD: str = "changethis"

    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "infrascope"
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5

    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 10
    UVICORN_WORKERS: int = 2
    ML_ENABLED: bool = True
    ML_SERVICE_URL: str = "http://ml-service:8010"
    POLLING_SERVICE_ENABLED: bool = False
    POLLING_SERVICE_URL: str = "http://polling-service:8011"
    # Backend-driven scheduled polling (Celery Beat), staggered per entity type
    # so the frontend no longer needs to trigger real device polls on a timer.
    AUTO_POLL_ENABLED: bool = True
    # Scheduled Wi-Fi AP reboot (VLAN 20 only, twice daily). Global kill switch
    # plus a store allowlist: a switch's own auto_reboot_aps_enabled toggle is
    # necessary but not sufficient - the store name must ALSO be listed here.
    # This is a live-hardware pilot (A30 first), so both gates default narrow.
    AUTO_REBOOT_AP_ENABLED: bool = True
    AUTO_REBOOT_AP_ALLOWED_STORES: str = "A30"
    # Real Cisco APs routinely take well over a minute to fully boot and
    # reappear in CDP after a PoE cycle - a single fixed pause caused every
    # reboot to be logged as a false "did not reappear" failure even though
    # the AP had actually recovered fine. Poll repeatedly instead of a single
    # check after one fixed wait.
    AUTO_REBOOT_AP_PAUSE_SECONDS: int = 45
    AUTO_REBOOT_AP_VERIFY_MAX_WAIT_SECONDS: int = 240
    AUTO_REBOOT_AP_VERIFY_POLL_INTERVAL_SECONDS: int = 20
    AUTO_REBOOT_AP_MAX_PER_SWITCH: int = 20
    # VLANs used for camera/video-surveillance subnets. Cameras don't announce
    # themselves via CDP/LLDP, so identifying "camera ports" for a switch is
    # purely VLAN membership + link/PoE state, not device discovery - this is
    # manual-only (view ports, PoE-cycle one by hand), no scheduled auto-reboot.
    CAMERA_VLANS: str = "241,242,243,244,247"
    DISCOVERY_SERVICE_ENABLED: bool = False
    DISCOVERY_SERVICE_URL: str = "http://discovery-service:8012"
    NETWORK_CONTROL_SERVICE_ENABLED: bool = False
    NETWORK_CONTROL_SERVICE_URL: str = "http://network-control-service:8013"
    MEDIA_SERVICE_ENABLED: bool = False
    MEDIA_SERVICE_URL: str = "http://media-service:8014"
    MEDIA_CLIENT_TOKEN: str = ""
    MEDIA_LIBRARY_DIR: str = "/var/lib/infrascope/media-library"
    MEDIA_LIBRARY_MAX_UPLOAD_MB: int = 1024
    INTERNAL_SERVICE_TOKEN: str = ""
    INTERNAL_HTTP_TIMEOUT_SECONDS: float = 30.0
    INTERNAL_HTTP_RETRIES: int = 1
    INTERNAL_HTTP_RETRY_BACKOFF_SECONDS: float = 0.5
    KAFKA_ENABLED: bool = False
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_EVENT_TOPIC: str = "infrascope.events"
    OTEL_ENABLED: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://jaeger:4318/v1/traces"
    OTEL_SERVICE_NAMESPACE: str = "infrascope"
    PROMETHEUS_API_URL: str = "http://prometheus:9090"
    JAEGER_API_URL: str = "http://jaeger:16686"
    JAEGER_UI_URL: str = "http://127.0.0.1:16686"
    KAFKA_UI_URL: str = "http://127.0.0.1:8080"
    ML_MIN_TRAIN_ROWS: int = 50
    ML_RETRAIN_HOUR_UTC: int = 2
    ML_SCORE_INTERVAL_MINUTES: int = 30

    SCAN_SUBNET: str = ""
    SCAN_PORTS: str = "9100,631,80,443"
    SCAN_MAX_HOSTS: int = 4096
    SCAN_TCP_TIMEOUT: float = 1.0
    SCAN_TCP_RETRIES: int = 1
    SCAN_TCP_CONCURRENCY: int = 128
    POLL_JITTER_MAX_MS: int = 120
    POLL_OFFLINE_CONFIRMATIONS: int = 2
    POLL_CIRCUIT_FAILURE_THRESHOLD: int = 4
    POLL_CIRCUIT_OPEN_SECONDS: int = 45
    POLL_RESILIENCE_STATE_TTL_SECONDS: int = 7200
    PRINTER_POLL_MAX_WORKERS: int = 16
    # Laser printers poll every 15 min (see celery_app.py), but only need a
    # full SNMP toner walk this rarely - cycle N of every M is "full", the
    # rest are a cheap online/offline-only check. 4 == once an hour.
    PRINTER_FULL_POLL_EVERY_N_CYCLES: int = 4
    MEDIA_POLL_MAX_WORKERS: int = 12
    SWITCH_POLL_MAX_CONCURRENCY: int = 8
    COMPUTER_POLL_CONCURRENCY: int = 16
    CASH_REGISTER_POLL_CONCURRENCY: int = 16
    NETWORK_PROBE_MAX_ATTEMPTS: int = 2
    NETWORK_PROBE_RETRY_BACKOFF_SECONDS: float = 0.15
    NETWORK_PROBE_TIMEOUT_MULTIPLIER: float = 1.25

    DOMAIN: str = "infrascope.local"
    DNS_SERVER: str = ""
    DNS_SEARCH_SUFFIXES: str = ""
    QR_SQL_LOGIN: str = ""
    QR_SQL_PASSWORD: str = ""
    QR_SQL_DUTY_FREE_SERVER: str = "10.10.94.228"
    QR_SQL_DUTY_FREE_DATABASE: str = ""
    QR_SQL_DUTY_PAID_SERVER: str = "10.10.94.229"
    QR_SQL_DUTY_PAID_DATABASE: str = ""
    QR_SQL_DATABASE: str = "CashDB51"
    QR_SQL_TIMEOUT_SECONDS: float = 20.0
    QR_EXPORT_TIMEOUT_SECONDS: float = 180.0
    ONEC_DUTY_FREE_API_URL: str = ""
    ONEC_DUTY_FREE_API_TOKEN: str = ""
    ONEC_DUTY_PAID_API_URL: str = ""
    ONEC_DUTY_PAID_API_TOKEN: str = ""
    ONEC_DUTY_FREE_IB_CONNECTION: str = ""
    ONEC_DUTY_FREE_DOMAIN: str = "regstaer-m"
    ONEC_DUTY_FREE_TERMINAL_SERVER: str = ""
    ONEC_DUTY_PAID_IB_CONNECTION: str = ""
    ONEC_DUTY_PAID_DOMAIN: str = "regstaer"
    ONEC_DUTY_PAID_TERMINAL_SERVER: str = ""
    ONEC_EXCHANGE_API_URL: str = ""
    ONEC_EXCHANGE_API_TOKEN: str = ""
    ONEC_EXCHANGE_TIMEOUT_SECONDS: float = 20.0
    HONEST_SIGN_ALLOWED_EMAILS: str = "golubchikovka@regstaer.ru"
    HONEST_SIGN_TARGETS: str = ""
    HONEST_SIGN_API_LOGIN: str = ""
    HONEST_SIGN_API_PASSWORD: str = ""
    HONEST_SIGN_TOKEN: str = ""
    HONEST_SIGN_PORT: int = 5995
    HONEST_SIGN_TIMEOUT_SECONDS: float = 10.0
    HONEST_SIGN_STATUS_WAIT_SECONDS: float = 15.0
    HONEST_SIGN_MAX_CONCURRENCY: int = 32
    SWITCH_WRITE_LOCK_SECONDS: int = 20
    SWITCH_SAFETY_COOLDOWN_SECONDS: int = 8

    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    BACKEND_TRUSTED_HOSTS: list[str] = ["localhost", "127.0.0.1", "::1", "testserver"]
    ENABLE_SECURITY_HEADERS: bool = True

    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_SERVER,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @computed_field
    @property
    def ASYNC_DATABASE_URI(self) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_SERVER,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )


settings = Settings()
