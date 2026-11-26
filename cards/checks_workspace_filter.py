"""
Temporary allowlist for the recurring background checks (exercises/apps.py:
role reminders, backup timeout activation, leaver alerts, scheduled AI
runs, AI decision escalation).

On request: every workspace that already existed at the time this was
added is EXCLUDED from these checks except "loca" (T0CLTSG8Y0N), which
is actively being tested. Any workspace created AFTER this snapshot --
today's "loca" itself already included, and every future test workspace
-- is never in this set, so the checks run for it normally. Remove this
file (and its two call sites) once the cleanup of old test workspaces is
no longer needed.
"""

_EXCLUDED_TEAM_IDS = {
    "T0BS9K6MT6G", "T0BUU27SA2H", "T0BV2UV4Q3W", "T0BV09Z395G", "T0BUWF219GV",
    "T0BV7SJRLJ3", "T0C13Q3B2E4", "T0BV8G0LEFR", "T0C09TB7UCA", "T0C0M3XRZU4",
    "T0C0Q4K4M1V", "T0C26F29PJA", "T0C2JPUL76E", "T0C2GV90H5L", "T0C2JSFMSV8",
    "T0C3LGVTBKK", "T0C3M20FNTB", "T0C3LEZPREW", "T0C3EDW671R", "T0C3JQB5PRC",
    "T0C4F757V4G", "T0C35PPGK0X", "T0C4MQJDZTJ", "T0C4RG10T8D", "T0C61CGA1K6",
    "T0C5RJBKHEX", "T0C5VSV495L", "T0C5T7XN3K7", "T0C64RLK46A", "T0C6R9NJJAW",
    "T0C6PGGJKJS", "T0C79AFHLNA", "T0CA2EJ1CKD", "T0CC3MD9VRN", "T0CBD80LQUU",
    "T0CB2K5VD2T", "T0CF0RHF5E2", "T0CF5AMGX33", "T0CEN3KA607", "T0CJFG3JG76",
    "T0CK6AQRZAL", "T0CLWMFKW8H", "T0CLNK2PH3M", "T0CLSUDHAKY", "T0CLZC2Q0TE",
    "T0CM5RK5NEM",
}


def checks_enabled_for(team_id: str) -> bool:
    return team_id not in _EXCLUDED_TEAM_IDS
