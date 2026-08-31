$ErrorActionPreference = "Stop"

python -m pip check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m ruff check web core/post_queue.py core/schedule_service.py core/database_maintenance.py core/data_cleanup.py core/job_states.py manage_database.py utils/secure_store.py tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m mypy web/models.py web/security.py web/ws_manager.py core/schedule_service.py core/database_maintenance.py core/data_cleanup.py core/job_states.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m coverage erase
python -m coverage run -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m coverage report
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
node --check web/static/app.js
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
