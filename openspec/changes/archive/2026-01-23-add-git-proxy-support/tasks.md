## 1. Backend Implementation
- 1.1 **Database Migration**: Add `proxy_url` field to `Repository` model in `server/projects/models.py`.
- 1.2 **System Settings**: Add `git_http_proxy` to allowed keys in `server/core/models.py`.
- 1.3 **API**: Update `Repository` serializers to include `proxy_url`.
- 1.4 **Task Scheduler**: Implement proxy resolution logic (Repo > System) in `server/services/task_scheduler.py`.
- 1.5 **Task CLI**: Ensure `friday-task` accepts and uses the passed proxy configuration.
## 2. Frontend Implementation
- 2.1 **System Settings**: Add input field for `git_http_proxy` in System Settings page.
- 2.2 **Repository Management**: Add input field for `proxy_url` in Repository Create/Edit forms.
## 3. Documentation
- 3.1 Update user guide to explain Git proxy configuration hierarchy.
