from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["*"]
STORAGES["staticfiles"]["BACKEND"] = "whitenoise.storage.CompressedStaticFilesStorage"  # noqa: F405
