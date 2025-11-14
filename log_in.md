- ERPNext already has multi-user auth built in: every user/app call needs API keys or session cookies tied to an
    ERPNext User record. For the bot, you’d create a service user API key plus a mapping table (Telegram user ID ↔
    ERPNext customer/employee). The service user posts on behalf of the company but still tags each journal entry with
    the originating user info for auditing (expense_attempts already tracks thread/user IDs, so you can include that
    in ERPNext custom fields).
  - If you want true row-level security, ERPNext supports role and permission managers where you can assign
    DocType-level restrictions (e.g., only see Journal Entries you created). For deeper isolation, you can create
    custom DocTypes or per-user filters. “Row-level security” in ERPNext is mostly done via permissions + “User
    Permissions” (filters by company, customer, etc.), not database-native RLS.
  - Telegram auth: normally you match on Telegram user ID (a numeric ID) rather than phone number, because phone
    access can be spoofed or hidden and bot APIs don’t expose it. During onboarding, you can ask the user to enter a
    one-time code the finance team generated; once entered, you store the mapping telegram_user_id -> erpnext_user_id.
    Every message coming from that Telegram ID then inherits the ERPNext identity and allowed actions.
  - To keep users scoped to “their own stuff,” you’d design your ERP queries to include the mapped user ID (e.g.,
    fetch only journals where owner = <user> or employee = <user>), and enforce the same on the bot side. ERPNext
    permissions can also enforce that server-side so users can’t pull data outside their scope even if the bot
    misbehaves.
  - If you eventually let users read data directly (e.g., “show my recent expenses”), you can either:
      1. Continue proxying through the bot’s service credentials but filter results per mapped user, or
      2. Generate individual ERPNext API tokens per user and store them encrypted (more secure but heavier ops).

  So the flow is: Telegram user authenticates once (code → mapping), bot uses that mapping each time, ERPNext
  permissions or filtered queries enforce “only my records,” and audit fields in ERPNext keep everything traceable.