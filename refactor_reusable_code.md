Before making any changes, create a backup of all files you intend to modify (e.g. copy them with a .bak extension or duplicate the directory).

Then:

1. Fix the bug by identifying the duplicated or divergent logic causing it. Refactor so all affected code paths share a single, well-named reusable function/module instead of maintaining separate copies.

2. Audit the rest of the codebase for similar opportunities — repeated logic, copy-pasted blocks, or tightly coupled code that would benefit from extraction into shared utilities, hooks, helpers, or modules.

3. Refactor those too, ensuring:
   - Each extracted unit has a single clear responsibility
   - Naming is explicit and intention-revealing
   - Existing behaviour is preserved exactly (no silent logic changes)
   - Any removed duplication is fully replaced, not just commented out

4. List every file changed, what was extracted, and where it now lives.

5. After testing, update the development docs to reflect:
   - Any new shared functions/modules (name, purpose, parameters, return values)
   - Where they live and how to use them
   - Any patterns or conventions introduced by this refactor that future code should follow
