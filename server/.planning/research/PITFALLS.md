# Domain Pitfalls: Django App Removal (Task to Workflow Migration)
**Domain:** Django app consolidation / system migration
**Researched:** 2026-02-01
**Confidence:** HIGH (verified with Django 6.0 documentation and codebase analysis)
## Project-Specific Context
This migration involves:
- Removing `server/tasks/` Django app (currently empty except migrations folder)
- Modifying `feishu/` app to use `workflows/` instead of tasks
- Cleaning up Task database tables (if any exist)
- Removing frontend Task pages
- Keeping `task/` independent executor (different from `server/tasks/`)
**Key Observation:** The `server/tasks/` app appears to already be empty (no models.py, views.py, etc.) - only contains `migrations/` and `__pycache__/`. This suggests the migration may already be partially complete, but the app directory and INSTALLED_APPS entry may still need cleanup.
---
## Critical Pitfalls
Mistakes that cause data loss, broken deployments, or require rollbacks.
### Pitfall 1: Premature App Directory Deletion
**What goes wrong:** Deleting the `server/tasks/` directory before running migrations that drop the tables. Django cannot find migration files needed to cleanly remove database tables.
**Why it happens:** Developers assume "the app is empty, I can just delete it" without realizing:
1. Migration history in `django_migrations` table still references the app
2. Database tables may still exist even if models.py is empty
3. Other apps may have dependencies on these migrations
**Consequences:**
- `migrate` command fails with "Migration X dependencies reference nonexistent parent node"
- Database tables become orphaned (exist but unmanaged)
- Future migrations may fail unpredictably
**Prevention:**
1. Check database for existing tables: `python manage.py dbshell` then `SELECT * FROM django_migrations WHERE app='tasks';`
2. Create final migration to drop any remaining tables BEFORE deleting app
3. Run `python manage.py migrate tasks zero --fake` if tables already removed manually
4. Only then remove from INSTALLED_APPS and delete directory
**Detection:**
- Migration errors mentioning "tasks" app
- Orphaned tables in database starting with `tasks_`
- `showmigrations` showing inconsistent state
**Phase:** Should be addressed in the Database Cleanup phase, before any code deletion.
---
### Pitfall 2: Foreign Key Constraint Violations
**What goes wrong:** Attempting to drop tables that are referenced by foreign keys in other apps, or removing an app while other models still reference it.
**Why it happens:** In this project, `WorkflowExecution` has a FK to `feishu.TriggerLog`, and there may be historical references from Task models to other entities.
**Consequences:**
- Database integrity errors during migration
- `IntegrityError: FOREIGN KEY constraint failed`
- Cascading deletes that remove unintended data
**Prevention:**
1. Map ALL foreign key relationships before starting:
 ```bash
 grep -r "ForeignKey.*tasks\." server/
 grep -r "models.ForeignKey" server/tasks/ 2>/dev/null
 ```
2. For FKs pointing TO tasks models: Update or remove these fields first
3. For FKs pointing FROM tasks models: Ensure `on_delete` behavior is acceptable
4. Create migration to remove FK constraints before table drops
**Detection:**
- Database constraint errors during migrate
- `FOREIGN KEY constraint failed` errors
- Related objects unexpectedly deleted
**Phase:** Must be verified in Research phase, addressed in Backend Migration phase.
---
### Pitfall 3: django_migrations Table Pollution
**What goes wrong:** After removing an app, entries remain in `django_migrations` table referencing non-existent migration files. Future migrations or fresh installs may fail.
**Why it happens:** Django tracks applied migrations in `django_migrations` table. Deleting migration files without cleaning this table leaves orphaned entries.
**Consequences:**
- `makemigrations` may generate incorrect dependencies
- Fresh database setup fails (references missing migrations)
- `migrate --prune` needed but forgotten
**Prevention:**
1. After removing app, run: `python manage.py migrate --prune` (Django 6.0+)
2. Or manually clean: `DELETE FROM django_migrations WHERE app='tasks';`
3. Document the cleanup step in migration instructions
**Detection:**
- `showmigrations` shows `[X]` for non-existent migration files
- New environment setup fails
- `migrate` warns about missing migration files
**Phase:** Database Cleanup phase, immediately after app removal.
---
### Pitfall 4: Content Type and Permission Stale Data
**What goes wrong:** Django's `contenttypes` framework maintains records for each model. Removing models without cleanup leaves stale ContentType and Permission records.
**Why it happens:** `django.contrib.contenttypes` tracks all models. When models are removed, their ContentType records persist.
**Consequences:**
- Stale data in `django_content_type` table
- Generic foreign keys pointing to non-existent models
- Admin permission issues
**Prevention:**
1. After migrations complete, run: `python manage.py remove_stale_contenttypes`
2. Review and confirm deletions when prompted
3. Also check: `python manage.py check` for any warnings
**Detection:**
- `django_content_type` contains entries for `tasks` app
- Admin shows orphaned permissions
- Generic FK lookups fail silently
**Phase:** Database Cleanup phase, after table removal.
---
## Moderate Pitfalls
Mistakes that cause delays, require rework, or create technical debt.
### Pitfall 5: Frontend-Backend State Desync
**What goes wrong:** Frontend still makes API calls to removed endpoints, or displays Task-related UI elements that no longer function.
**Why it happens:** Backend and frontend changes not deployed atomically, or incomplete search for Task references in frontend code.
**Consequences:**
- 404 errors in production
- Broken UI elements
- User confusion
**Prevention:**
1. Search frontend thoroughly:
 ```bash
 grep -r "task\|Task" web/src/ --include="*.vue" --include="*.ts"
 ```
2. The current codebase shows 17 files with task/Task references - each needs review
3. Deploy frontend and backend changes together
4. Use feature flags to gate changes (already in settings.py: `FF_USE_WORKFLOW_FOR_NEW_TASKS`)
**Detection:**
- Console errors for failed API calls
- Empty UI sections
- User reports of broken features
**Phase:** Frontend Cleanup phase, must coordinate with Backend Migration.
---
### Pitfall 6: Incomplete Reference Cleanup in Backend
**What goes wrong:** Import statements, URL patterns, or string references to the removed app remain, causing runtime errors.
**Why it happens:** Grep searches miss dynamic imports, string-based model references, or settings entries.
**Consequences:**
- `ImportError` on startup
- `LookupError: App 'tasks' not installed`
- Broken URL routing
**Prevention:**
1. Check INSTALLED_APPS in settings.py (currently `tasks` is NOT listed - good)
2. Search for all references:
 ```bash
 grep -r "from tasks" server/
 grep -r "import tasks" server/
 grep -r "'tasks\." server/
 grep -r '"tasks\.' server/
 ```
3. Check URL configurations for task-related routes
4. Run full test suite before deployment
**Detection:**
- Application fails to start
- Specific views return 500 errors
- Tests fail with import errors
**Phase:** Backend Migration phase.
---
### Pitfall 7: Test Suite Breakage
**What goes wrong:** Tests reference removed models, fixtures, or endpoints, causing test failures that block deployment.
**Why it happens:** Test files often lag behind production code changes. Tests in `server/tests/` may still test Task functionality.
**Consequences:**
- CI/CD pipeline blocked
- False confidence if tests are skipped
- Regressions go unnoticed
**Prevention:**
1. Audit test files:
 ```bash
 grep -r "task\|Task" server/tests/
 ```
2. Remove or update Task-related tests
3. Add new tests for Workflow equivalents
4. Run full test suite locally before PR
**Detection:**
- pytest failures mentioning tasks
- Import errors in test files
- Fixture loading failures
**Phase:** Testing phase, parallel with Backend Migration.
---
### Pitfall 8: Confusion Between server/tasks/ and task/ Executor
**What goes wrong:** Developer accidentally modifies or removes the independent `task/` executor directory instead of `server/tasks/` Django app.
**Why it happens:** Similar naming. The project has:
- `server/tasks/` - Django app being removed
- `task/` (if exists) - Independent executor, should be kept
**Consequences:**
- Critical functionality removed
- Production task execution fails
- Difficult to recover if not in version control
**Prevention:**
1. Document the distinction clearly in migration Plan. Use explicit paths in all commands
3. Review PRs carefully for accidental changes to wrong directory
4. Confirm `task/` executor functionality works after migration
**Detection:**
- Task execution stops working
- Unexpected files in git diff
- Error logs from executor
**Phase:** All phases - ongoing awareness required.
---
## Minor Pitfalls
Mistakes that cause annoyance but are easily fixable.
### Pitfall 9: Lingering Configuration and Feature Flags
**What goes wrong:** Feature flags like `FF_USE_WORKFLOW_FOR_NEW_TASKS` and `FF_ENABLE_TASK_COMPAT_API` remain in settings.py after migration is complete.
**Why it happens:** Flags added for gradual migration are forgotten after migration completes.
**Consequences:**
- Code complexity
- Confusion for new developers
- Unused configuration cluttering settings
**Prevention:**
1. Document all migration-related flags
2. Create cleanup ticket for post-migration
3. Remove flags after migration is stable (e.g., 2 weeks in production)
**Detection:**
- Settings.py contains unused `FF_*` variables
- Code contains dead branches for old path
**Phase:** Post-Migration Cleanup phase.
---
### Pitfall 10: Incomplete Documentation Updates
**What goes wrong:** README, API docs, or inline comments still reference Task system.
**Why it happens:** Documentation is often an afterthought.
**Consequences:**
- Developer confusion
- Incorrect API usage
- Onboarding difficulties
**Prevention:**
1. Search all markdown files: `grep -r "task\|Task" *.md`
2. Update API documentation (drf-spectacular annotations)
3. Review developer-notes.md for outdated references
**Detection:**
- New developers ask about Task system
- API docs show non-existent endpoints
**Phase:** Documentation phase, after code changes complete.
---
## Phase-Specific Warnings
| Phase | Likely Pitfall | Mitigation |
|-------|---------------|------------|
| Research/Planning | #8 Confusion between tasks/ directories | Clear documentation of what to remove vs keep |
| Database Cleanup | #1 Premature deletion, #2 FK violations, #3 Migration pollution | Verify database state first, create proper migrations |
| Backend Migration | #2 FK violations, #6 Incomplete cleanup | Comprehensive grep searches, test startup |
| Frontend Cleanup | #5 State desync | Coordinate deployment, use feature flags |
| Testing | #7 Test breakage | Run full suite, update tests |
| Post-Migration | #4 Content type cleanup, #9 Flag cleanup | Run Django management commands |
---
## Migration Order Recommendation
Based on pitfall analysis, recommended phase order:
1. **Verification Phase**
 - Confirm `server/tasks/` is truly empty (no models)
 - Check `django_migrations` for tasks entries
 - Map any FK relationships
2. **Database Cleanup Phase**
 - Run `migrate tasks zero --fake` if needed
 - Clean `django_migrations` table
 - Run `remove_stale_contenttypes`
3. **Backend Code Cleanup Phase**
 - Remove `tasks` from INSTALLED_APPS (if present)
 - Remove `server/tasks/` directory
 - Update any remaining references
4. **Frontend Cleanup Phase**
 - Update/remove Task UI components
 - Update API calls
 - Coordinate deployment
5. **Testing Phase**
 - Update test suite
 - Run full integration tests
6. **Post-Migration Cleanup**
 - Remove feature flags
 - Update documentation
---
## Sources
- [Django Documentation - Migrations](https://docs.djangoproject.com/en/6.0/topics/migrations/)
- [Django Documentation - migrate --prune](https://docs.djangoproject.com/en/6.0/ref/django-admin/#cmdoption-migrate-prune)
- [Simple is Better Than Complex - How to Reset Migrations](https://simpleisbetterthancomplex.com/tutorial/2016/07/26/how-to-reset-migrations.html)
- [Stack Overflow - Django app removal best practices](https://stackoverflow.com/questions/tagged/django-migrations)
- Codebase analysis: `/Users/zaneliu/Projects/open-source/friday-ai/server/`
