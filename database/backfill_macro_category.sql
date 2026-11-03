-- Fills system_skills_registry.macro_category where a seeded row has NULL.
-- Progress events carry this number; the UI maps it to a stage (App.tsx MACRO_CATEGORY_TO_STAGE).
-- Same mapping as scripts/import_manifest.py _MACRO_NUMBER. Safe to re-run.
UPDATE system_skills_registry SET macro_category = CASE macro_category_name
    WHEN 'intake' THEN 1
    WHEN 'extraction' THEN 2
    WHEN 'pricing' THEN 3
    WHEN 'erpDataSync' THEN 4
    WHEN 'risk' THEN 5
    WHEN 'pricingConsolidation' THEN 6
    WHEN 'priceDecision' THEN 7
    WHEN 'quoteReadiness' THEN 8
    WHEN 'reportingAnalytics' THEN 9
  END
WHERE macro_category IS NULL;
