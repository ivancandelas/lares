from .base import *  # noqa: F403

DEBUG = True

# Sin worker en desarrollo: las tareas se ejecutan en el acto.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = False
ALLOWED_HOSTS = ["*"]
STORAGES["staticfiles"]["BACKEND"] = "whitenoise.storage.CompressedStaticFilesStorage"  # noqa: F405
