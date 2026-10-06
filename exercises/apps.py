import logging
import os
import threading
import time

from django.apps import AppConfig

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60


class ExercisesConfig(AppConfig):
    name = "exercises"

    def ready(self):
        # Step 5 (backup fallback) needs *something* checking "has time run
        # out on this task?" on a recurring basis -- no Celery/cron set up
        # in this project yet, so a simple daemon thread inside the same
        # dev server process is the lightest way to get real escalation
        # working without adding new infrastructure.
        #
        # RUN_MAIN guard: Django's autoreloader spawns a watcher process
        # that also imports every app -- without this check the thread
        # would start twice (once in the watcher, once in the real
        # server), each pair of escalations firing twice.
        if os.environ.get("RUN_MAIN") != "true":
            return

        def _loop():
            # Import inside the thread, not at module load -- avoids
            # touching Django/Mongo models before the app registry (and
            # the Mongo connection) has finished setting up.
            from .drill import escalate_overdue_tasks

            while True:
                time.sleep(CHECK_INTERVAL_SECONDS)
                try:
                    count = escalate_overdue_tasks()
                    if count:
                        logger.info("Escalated %d overdue drill task(s) to backup", count)
                except Exception:
                    logger.exception("Drill escalation check failed")

        threading.Thread(target=_loop, daemon=True, name="drill-escalation-checker").start()
