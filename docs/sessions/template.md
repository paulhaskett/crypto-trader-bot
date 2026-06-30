# Session Template

Use this template for documenting each development session.

---

```markdown
# Session: vX.X.X - [Brief Title]

**Date**: [Date]

## Changes Made

| File | Change |
|------|--------|
| `src/xxx.py` | Description of change |

## API Endpoints Added/Modified

- `GET /api/xxx` - Purpose
- `POST /api/xxx` - Purpose

## Settings Changes

| Setting | Old Value | New Value |
|---------|-----------|-----------|
| `SETTING_NAME` | `old` | `new` |

## Testing

- [ ] Verified X works
- [ ] Need to verify Y

## Decisions Made

- [Chosen approach] → [Reason]

## Follow-up Items

- [ ] Future improvement or bug fix
```

---

## Guidelines

1. **Date**: Use ISO format (YYYY-MM-DD)
2. **Version**: Increment from previous session
3. **Changes**: Be specific about files and what changed
4. **API Endpoints**: Document any new endpoints
5. **Settings**: Note any configuration changes
6. **Testing**: Mark completed tests with `[x]`
7. **Decisions**: Explain why choices were made
8. **Follow-up**: List future work

## After Each Session

1. Create session file in `docs/sessions/`
2. Update `docs/index.md` changelog if needed
3. Update `docs/api-reference.md` if endpoints changed
4. Update `docs/settings.md` if settings changed
