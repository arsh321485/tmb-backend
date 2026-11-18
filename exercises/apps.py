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
            from cards.role_reminders_v2 import check_backup_timeout_activation, check_role_reminders, check_leavers
            from cards.ai_drill_v2 import check_scheduled_ai_runs, escalate_overdue_ai_decisions

            while True:
                time.sleep(CHECK_INTERVAL_SECONDS)
                try:
                    decisions_count = escalate_overdue_ai_decisions()
                    if decisions_count:
                        logger.info("Escalated/timed out %d overdue AI decision(s)", decisions_count)
                except Exception:
                    logger.exception("AI decision escalation check failed")

                try:
                    reminders_count = check_role_reminders()
                    if reminders_count:
                        logger.info("Sent %d role reminder/escalation message(s)", reminders_count)
                except Exception:
                    logger.exception("Role reminder check failed")

                try:
                    backup_activated_count = check_backup_timeout_activation()
                    if backup_activated_count:
                        logger.info("Activated %d backup(s) after primary timeout", backup_activated_count)
                except Exception:
                    logger.exception("Backup timeout activation check failed")

                try:
                    leaver_count = check_leavers()
                    if leaver_count:
                        logger.info("Sent %d leaver alert(s) to People & Roles owner", leaver_count)
                except Exception:
                    logger.exception("Leaver check failed")

                try:
                    ai_fired = check_scheduled_ai_runs()
                    if ai_fired:
                        logger.info("Fired %d scheduled AI scenario run(s)", ai_fired)
                except Exception:
                    logger.exception("Scheduled AI run check failed")

        threading.Thread(target=_loop, daemon=True, name="drill-escalation-checker").start()
