"""Settings for the example project. The test settings add the model endpoint."""

SECRET_KEY = "only-for-tests"  # pragma: allowlist secret
DEBUG = False
ALLOWED_HOSTS: list[str] = []
INSTALLED_APPS = ["pipeline.apps.PipelineConfig"]
DATABASES: dict[str, dict[str, str]] = {}
USE_TZ = True
